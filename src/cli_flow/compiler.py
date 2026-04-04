"""Compile a flow YAML file into a self-contained Python zipapp executable.

The compiled artifact:
- Bundles the flow YAML and the cli_flow runtime into a single file
- Is directly executable: ./my-flow --repo foo/bar --target ~/dev
- Requires Python 3.11+ on the target machine
- With --bundle-deps: requires only Python 3.11+ (PyYAML and Jinja2 vendored in)

How it works:
  zipapp.create_archive() turns a directory into a .pyz file with a shebang.
  The directory must contain a __main__.py that is the entry point.
  We build that directory in a TemporaryDirectory so nothing is left on disk.

The embedded __main__.py uses importlib.resources to read the bundled flow.yaml,
which correctly handles the virtual paths inside a zipapp (unlike open() or __file__).
"""

from __future__ import annotations

import importlib.resources
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import zipapp
from pathlib import Path

from cli_flow.errors import PreflightError, SchemaError
from cli_flow.loader import load_flow


# Template for the __main__.py that gets embedded in the compiled artifact.
#
# flow.yaml is placed inside a _bundled package (with __init__.py) so that
# importlib.resources.files("_bundled") resolves correctly inside the zipapp.
# Using "." as the anchor does not work from __main__ because it requires a
# package context; a named package with an __init__.py is the correct approach.
_MAIN_TEMPLATE = textwrap.dedent("""\
    import sys
    import os

    {vendor_path_setup}

    import importlib.resources

    # Read the bundled flow YAML from the _bundled package.
    # importlib.resources.files() returns a zipfile.Path when run inside a
    # zipapp, so this works correctly without touching the real filesystem.
    flow_yaml = (
        importlib.resources.files("_bundled")
        .joinpath("flow.yaml")
        .read_text(encoding="utf-8")
    )

    from cli_flow.cli import run_compiled
    run_compiled(flow_yaml, sys.argv[1:])
""")

_VENDOR_PATH_SETUP = textwrap.dedent("""\
    # Prepend vendored dependencies so they take priority over system packages.
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(_here, "vendor"))
""")


def compile_flow(flow_path: str, output_path: str, bundle_deps: bool) -> None:
    """Compile a flow YAML into a standalone executable zipapp.

    Raises SchemaError if the flow file is invalid.
    Raises PreflightError if bundling dependencies fails.
    """
    # Validate the flow file before doing any build work
    load_flow(flow_path)

    with tempfile.TemporaryDirectory() as build_dir:
        _build_artifact(flow_path, output_path, bundle_deps, Path(build_dir))


def _build_artifact(
    flow_path: str,
    output_path: str,
    bundle_deps: bool,
    build_dir: Path,
) -> None:
    # 1. Copy the cli_flow package into the build dir
    package_src = Path(__file__).parent
    package_dst = build_dir / "cli_flow"
    shutil.copytree(package_src, package_dst)

    # 2. Copy the flow YAML into a _bundled package so importlib.resources
    #    can locate it by package name inside the zipapp.
    bundled_dir = build_dir / "_bundled"
    bundled_dir.mkdir()
    (bundled_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(flow_path, bundled_dir / "flow.yaml")

    # 3. Optionally vendor PyYAML and Jinja2
    if bundle_deps:
        _vendor_dependencies(build_dir)
        vendor_setup = _VENDOR_PATH_SETUP
    else:
        vendor_setup = ""

    # 4. Write the embedded __main__.py
    main_content = _MAIN_TEMPLATE.format(vendor_path_setup=vendor_setup)
    (build_dir / "__main__.py").write_text(main_content, encoding="utf-8")

    # 5. Create the zipapp
    zipapp.create_archive(
        source=str(build_dir),
        target=output_path,
        interpreter="/usr/bin/env python3",
    )

    # 6. Make the artifact executable
    current = os.stat(output_path).st_mode
    os.chmod(output_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _vendor_dependencies(build_dir: Path) -> None:
    """Install PyYAML and Jinja2 as pure-Python wheels into build_dir/vendor.

    --no-binary :all: forces pure-Python wheels. C extensions (.so/.pyd files)
    cannot be loaded from inside a zipapp, so this is required.
    """
    vendor_dir = build_dir / "vendor"
    vendor_dir.mkdir()

    cmd = [
        sys.executable, "-m", "pip", "install",
        "--target", str(vendor_dir),
        "--no-binary", ":all:",
        "--quiet",
        "PyYAML",
        "Jinja2",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PreflightError(
            f"Failed to vendor dependencies:\n{result.stderr}"
        )


def default_output_name(flow_name: str) -> str:
    """Derive the default output filename from the flow's display name.

    'Developer Onboarding' -> 'developer-onboarding'
    """
    return re.sub(r"\s+", "-", flow_name.strip()).lower()
