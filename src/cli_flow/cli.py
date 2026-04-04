"""Top-level CLI: argparse setup and subcommand dispatch."""

from __future__ import annotations

import argparse
import os
import sys

from cli_flow import output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli-flow",
        description="YAML-driven CLI orchestrator for repeatable workflows.",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--verbose", action="store_true", help="Print each command before running it")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # run
    run_parser = subparsers.add_parser("run", help="Run a flow file")
    run_parser.add_argument("file", help="Path to the flow YAML file")
    run_parser.add_argument("--dry-run", action="store_true", help="Print rendered commands without executing")
    run_parser.add_argument("--step", metavar="<name>", help="Run a single named step (skips dependency check)")
    run_parser.add_argument(
        "--var",
        metavar="key=value",
        action="append",
        dest="vars",
        help="Override a variable (can be used multiple times)",
    )

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate a flow file without executing")
    validate_parser.add_argument("file", help="Path to the flow YAML file")

    # list
    list_parser = subparsers.add_parser("list", help="List steps and their descriptions")
    list_parser.add_argument("file", help="Path to the flow YAML file")

    # init
    subparsers.add_parser("init", help="Scaffold a new flow file interactively")

    # compile
    compile_parser = subparsers.add_parser("compile", help="Compile a flow file into a standalone executable")
    compile_parser.add_argument("file", help="Path to the flow YAML file")
    compile_parser.add_argument("--output", metavar="<path>", help="Output path for the compiled artifact")
    compile_parser.add_argument(
        "--bundle-deps",
        action="store_true",
        help="Vendor PyYAML and Jinja2 into the artifact (zero deps beyond Python 3.11+)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.no_color:
        output.COLOR_ENABLED = False

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "compile":
        return _cmd_compile(args)

    parser.print_help()
    return 1


def run_compiled(flow_yaml: str, argv: list[str]) -> None:
    """Entry point for compiled artifacts.

    Accepts the flow YAML content as a string (already read by the zipapp
    bootstrap via importlib.resources) and runs the flow directly, bypassing
    subcommand routing.

    Handles a small set of runtime flags (--dry-run, --no-color, --step)
    before passing the remaining argv to the flow's argument parser.
    """
    from cli_flow.loader import load_flow_from_string
    from cli_flow.arguments import resolve_arguments
    from cli_flow.dependencies import assert_dependencies
    from cli_flow.executor import run_flow

    # Parse runtime flags that apply to the compiled artifact itself.
    # We use a separate parser so these don't interfere with flow arguments.
    runtime_parser = argparse.ArgumentParser(add_help=False)
    runtime_parser.add_argument("--dry-run", action="store_true", default=False)
    runtime_parser.add_argument("--no-color", action="store_true", default=False)
    runtime_parser.add_argument("--step", default=None)
    runtime_args, flow_argv = runtime_parser.parse_known_args(argv)

    if runtime_args.no_color:
        output.COLOR_ENABLED = False

    try:
        flow = load_flow_from_string(flow_yaml, source="<bundled>")
        context = resolve_arguments(flow, flow_argv)
        if not runtime_args.step:
            assert_dependencies(flow.workflow.depends_on)
        exit_code = run_flow(
            flow,
            context,
            dry_run=runtime_args.dry_run,
            single_step=runtime_args.step,
        )
    except Exception as exc:
        output.print_preflight_error(str(exc))
        sys.exit(1)

    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_run(args: argparse.Namespace) -> int:
    from cli_flow.loader import load_flow
    from cli_flow.arguments import resolve_arguments
    from cli_flow.dependencies import assert_dependencies
    from cli_flow.executor import run_flow
    from cli_flow.errors import SchemaError, PreflightError

    try:
        flow = load_flow(args.file)
    except SchemaError as exc:
        output.print_preflight_error(str(exc))
        return 1

    # Collect flow arguments from the remaining argv (everything after the file).
    # argparse has already consumed --dry-run, --step, --var, and --no-color.
    # We rebuild the flow-specific argv from --var overrides only, since the
    # flow arguments are passed after the file positional on the command line.
    # The actual flow argv is sys.argv sliced past "run <file>".
    import sys as _sys
    try:
        file_index = _sys.argv.index(args.file)
    except ValueError:
        file_index = 2
    flow_argv = _sys.argv[file_index + 1:]

    # Strip out cli-flow global flags from flow_argv
    _global_flags = {"--dry-run", "--no-color", "--verbose"}
    flow_argv = [
        a for i, a in enumerate(flow_argv)
        if a not in _global_flags
        and not (i > 0 and flow_argv[i - 1] in ("--step",))
    ]
    # Remove --step and its value
    if "--step" in flow_argv:
        idx = flow_argv.index("--step")
        flow_argv = flow_argv[:idx] + flow_argv[idx + 2:]

    try:
        context = resolve_arguments(flow, flow_argv)
        if not args.step:
            assert_dependencies(flow.workflow.depends_on)
        exit_code = run_flow(flow, context, dry_run=args.dry_run, single_step=args.step)
    except PreflightError as exc:
        output.print_preflight_error(str(exc))
        return 1

    return exit_code


def _cmd_validate(args: argparse.Namespace) -> int:
    from cli_flow.loader import load_flow
    from cli_flow.errors import SchemaError

    try:
        load_flow(args.file)
        print(f"✓ {args.file} is valid")
        return 0
    except SchemaError as exc:
        output.print_preflight_error(str(exc))
        return 1


def _cmd_list(args: argparse.Namespace) -> int:
    from cli_flow.loader import load_flow
    from cli_flow.errors import SchemaError

    try:
        flow = load_flow(args.file)
    except SchemaError as exc:
        output.print_preflight_error(str(exc))
        return 1

    print(f"Steps in {args.file}:")
    for i, step in enumerate(flow.workflow.steps, start=1):
        desc = f"  {step.description}" if step.description else ""
        flags = []
        if step.soft_fail:
            flags.append("[soft-fail]")
        if step.condition:
            flags.append(f"[if: {step.condition}]")
        flag_str = "   " + " ".join(flags) if flags else ""
        print(f"  {i}  {step.name:<20}{desc}{flag_str}")

    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    import os

    print("Scaffolding a new flow file. Press Ctrl+C to cancel.\n")

    try:
        name = input("Flow name: ").strip() or "My Flow"
        version = input("Version [1.0.0]: ").strip() or "1.0.0"
        description = input("Description: ").strip() or "A workflow"
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    filename = name.lower().replace(" ", "-") + ".yaml"

    if os.path.exists(filename):
        try:
            confirm = input(f"\n'{filename}' already exists. Overwrite? [y/N]: ").strip().lower()
        except KeyboardInterrupt:
            print("\nAborted.")
            return 1
        if confirm != "y":
            print("Aborted.")
            return 1

    content = f"""\
name: "{name}"
version: "{version}"
description: "{description}"

arguments:
  # example:
  # myArg:
  #   type: string
  #   description: "What this argument does"
  #   required: true

workflow:
  dependsOn:
    - git
  steps:
    - name: hello
      description: "A starter step"
      command: "echo Hello from {name}"
"""

    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"\nCreated {filename}")
    print(f"Run with: cli-flow run {filename}")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    from cli_flow.compiler import compile_flow, default_output_name
    from cli_flow.loader import load_flow
    from cli_flow.errors import SchemaError, PreflightError

    # Determine output path: explicit --output or derived from the flow name
    output_path = args.output
    if not output_path:
        try:
            flow = load_flow(args.file)
        except SchemaError as exc:
            output.print_preflight_error(str(exc))
            return 1
        output_path = default_output_name(flow.name)

    try:
        compile_flow(args.file, output_path, bundle_deps=args.bundle_deps)
    except (SchemaError, PreflightError) as exc:
        output.print_preflight_error(str(exc))
        return 1

    size_kb = round(os.path.getsize(output_path) / 1024)
    print(f"Compiled: ./{output_path}  ({size_kb} KB)")
    print(f"Run with: ./{output_path} --help")
    return 0
