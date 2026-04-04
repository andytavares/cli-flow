# cli-flow — Technical Specification

## Stack

- **Language**: Python 3.11+
- **CLI framework**: `argparse` (stdlib) — no external CLI libs
- **YAML parsing**: `PyYAML` (pure-Python loader only — see Deliverable 9)
- **Template engine**: `Jinja2` — handles `{{ }}` expressions, ternaries, filters, and conditionals
- **Packaging**: `pyproject.toml` with `hatch` or `pip install -e .`
- **Distribution**: installable via `pip install cli-flow`; compiled artifacts are standalone `.pyz` files (Python zipapp)

---

## Project Layout

```
cli-flow/
├── pyproject.toml
├── src/
│   └── cli_flow/
│       ├── __main__.py        # Entry point: routes subcommands
│       ├── cli.py             # argparse setup and subcommand dispatch
│       ├── loader.py          # YAML loading and schema validation
│       ├── arguments.py       # Argument parsing, type coercion, defaults
│       ├── template.py        # Jinja2 template rendering
│       ├── dependencies.py    # dependsOn pre-flight checks
│       ├── executor.py        # Step execution loop
│       ├── compiler.py        # compile subcommand: produces .pyz artifacts
│       ├── output.py          # Colored terminal output helpers
│       └── errors.py          # Shared exception types
└── tests/
    ├── fixtures/              # Sample .yaml flow files for testing
    ├── test_loader.py
    ├── test_arguments.py
    ├── test_template.py
    ├── test_dependencies.py
    ├── test_executor.py
    └── test_compiler.py
```

---

## Deliverable 1 — Project Scaffold & CLI Entry Point

**Goal**: A working `cli-flow` command that routes to subcommands, even if those subcommands are stubs.

### Tasks

1. **Init `pyproject.toml`**
   - Package name: `cli-flow`, entry point: `cli-flow = cli_flow.__main__:main`
   - Dependencies: `PyYAML>=6.0`, `Jinja2>=3.1`
   - Dev dependencies: `pytest`, `pytest-cov`

2. **`__main__.py`**
   - Call `cli.main()` so the package is runnable via `python -m cli_flow` and via the installed `cli-flow` script

3. **`cli.py` — top-level argparse**
   - Root parser with subparsers: `run`, `validate`, `list`, `init`, `compile`
   - Global flags available on all subcommands: `--no-color`, `--verbose`
   - Each subcommand stub prints `"not yet implemented"` and exits 0
   - `--help` on any subcommand works immediately

**Acceptance**: `cli-flow --help`, `cli-flow run --help`, `cli-flow compile --help` all print usage without error.

---

## Deliverable 2 — YAML Loader & Schema Validation

**Goal**: Load a flow file and return a validated, typed Python dataclass tree. Reject invalid files with precise errors.

### Tasks

1. **Define dataclasses in `loader.py`**

   ```python
   # Sentinel used to distinguish "no default specified" from "default: null"
   _MISSING = object()

   @dataclass
   class Argument:
       name: str
       type: Literal["string", "boolean", "number", "enum"]
       description: str
       required: bool
       default: Any          # _MISSING = no default; None = explicit null default
       format: str | None    # display-only, no validation
       options: list[str] | None  # enum only

   @dataclass
   class Step:
       name: str
       command: str
       description: str | None
       soft_fail: bool              # default False
       condition: str | None        # Jinja2 expression string, or None
       workdir: str | None
       env: dict[str, str]          # empty dict if not set

   @dataclass
   class Workflow:
       depends_on: list[str]        # empty list if not set
       env: dict[str, str]          # empty dict if not set
       steps: list[Step]

   @dataclass
   class Flow:
       name: str
       version: str
       description: str
       arguments: list[Argument]
       workflow: Workflow
   ```

2. **`load_flow(path: str) -> Flow`**
   - Open and parse YAML using `yaml.safe_load` (pure-Python `SafeLoader` — never `CLoader`); raise `SchemaError` with file path and line hint if YAML is malformed
   - Validate required top-level keys: `name`, `version`, `description`, `workflow`
   - For each argument: validate `type` is one of the four allowed values; validate `options` is present iff `type == "enum"`; validate `default` is only set when `required == False`; store `_MISSING` when no `default` key is present in the YAML
   - For each step: validate `name` is unique within the flow; `soft_fail` defaults to `False` if absent
   - Return a fully populated `Flow` dataclass

3. **`errors.py`** — define shared exceptions:
   - `SchemaError(message, file, line=None)` — invalid YAML structure
   - `PreflightError(message)` — runtime pre-flight failures (type errors, missing args, missing deps)
   - `StepError(step_name, exit_code)` — step execution failure (stdout/stderr already streamed to terminal)

**Acceptance**: `load_flow("valid.yaml")` returns a `Flow`. `load_flow("bad.yaml")` raises `SchemaError` with a message pointing to the problem field. An argument with no `default` key in YAML has `default is _MISSING`.

---

## Deliverable 3 — Argument Parsing & Validation

**Goal**: Turn `sys.argv` flags into a resolved `dict[str, Any]` of variable values, with all type coercion and validation applied.

### Tasks

1. **`arguments.py` — `build_arg_parser(flow: Flow) -> argparse.ArgumentParser`**
   - For each `Argument` in `flow.arguments`, add a flag to the parser:
     - `type: boolean` → `add_argument("--name", action="store_true", default=False)`
     - `type: string` → `add_argument("--name", type=str, ...)`
     - `type: number` → use a custom coercion function: `int(x)` if `float(x).is_integer()`, else `float(x)`. This ensures `--port 8080` → `8080` (int) and `--ratio 1.5` → `1.5` (float), so template rendering produces `8080` not `8080.0`
     - `type: enum` → `add_argument("--name", choices=argument.options, ...)`
   - Mark `required: true` arguments as `required=True` in argparse
   - When `argument.default is not _MISSING`, set `default=argument.default` in argparse
   - Include `description` and `format` in the help string: `f"{description} (example: {format})"`

2. **`resolve_arguments(flow: Flow, argv: list[str]) -> dict[str, Any]`**
   - Build the parser, parse `argv`, return a dict keyed by argument name
   - After parsing, scan all step `command` and `condition` strings for variable references (see task 3); for any referenced name whose argument has `default is _MISSING` and was not provided by the user, collect into a list and raise a single `PreflightError` naming each step and variable

3. **Template reference scan** (called inside `resolve_arguments`)
   - Use Jinja2's AST parser to extract variable references: call `jinja2.Environment().parse(template)` and walk all `jinja2.nodes.Name` nodes in the resulting AST
   - This correctly handles nested expressions, quoted strings, and all other edge cases that regex cannot
   - Cross-reference the discovered names against the resolved argument dict; collect all violations before raising

**Acceptance**: Correct flags resolve to typed values. `--port 8080` produces `8080` (int), not `8080.0`. Missing required flags print usage and exit 1. Optional arg with `default is _MISSING` that is referenced in a template but not provided raises `PreflightError` listing all violations.

---

## Deliverable 4 — Template Rendering

**Goal**: Render `command` and `condition` strings using Jinja2 with the resolved argument dict as context.

### Tasks

1. **`template.py` — configure a shared Jinja2 `Environment`**
   - Standard `{{ }}` delimiters
   - `undefined = jinja2.StrictUndefined` — any unresolved variable raises immediately rather than rendering as empty string
   - Disable autoescaping (these are shell commands, not HTML)

2. **`render_command(command: str, context: dict) -> str`**
   - Apply the ternary preprocessor (see task 4) before rendering
   - Render the result with the context; catch `jinja2.UndefinedError` and re-raise as `PreflightError`

3. **`evaluate_condition(condition: str, context: dict) -> bool`**
   - Apply the ternary preprocessor, then render the condition string
   - Cast the rendered string to bool: `"false"` (case-insensitive), `"0"`, or `""` → `False`; anything else → `True`
   - Wrap `jinja2.UndefinedError` as `PreflightError`

4. **Ternary preprocessor**
   - JS-style ternary (`? :`) is not valid Jinja2. Implement `preprocess(template: str) -> str` that rewrites `{{ A ? B : C }}` to `{{ B if A else C }}` before passing to Jinja2
   - Use a regex with capture groups scoped to the inside of `{{ }}` delimiters
   - The `||` operator is **not** rewritten — authors must use Jinja2-native `or` directly: `{{ x or '.' }}`. This is documented in the authoring guide. Attempting to use `||` will produce a Jinja2 syntax error at render time with a clear message

**Supported template syntax (what authors write in YAML):**

| Feature            | YAML syntax                                  | Notes                          |
|--------------------|----------------------------------------------|--------------------------------|
| Variable reference | `{{ repo }}`                                 |                                |
| Ternary            | `{{ useHttps ? 'https://' : 'git@' }}`       | Preprocessed to `if/else`      |
| Fallback/default   | `{{ targetDir or '.' }}`                     | Native Jinja2 `or`             |
| String concat      | `{{ 'https://github.com/' + repo }}`         |                                |
| Comparison         | `{{ env == 'production' }}`                  |                                |

**Acceptance**: All five template features render correctly. `StrictUndefined` raises `PreflightError` on unknown variable. JS-style ternary is correctly rewritten. `||` in a template produces a clear Jinja2 syntax error.

---

## Deliverable 5 — Dependency Pre-flight Checks

**Goal**: Verify all `dependsOn` entries are available before any step runs.

### Tasks

1. **`dependencies.py` — `check_dependencies(depends_on: list[str]) -> list[str]`**
   - For each entry, run `<entry> --version` via `subprocess.run` with `stdout=PIPE`, `stderr=PIPE`, `timeout=5`
   - A zero exit code = available; non-zero or `FileNotFoundError` = missing
   - Return a list of all missing dependency strings (do not fail fast — collect all failures)

2. **`assert_dependencies(depends_on: list[str]) -> None`**
   - Call `check_dependencies`; if the list is non-empty, raise `PreflightError` with all missing entries listed

**Note on multi-word entries**: `"docker compose"` is split on the first space — binary = `docker`, args = `["compose", "--version"]`. Single-word entries run as `["git", "--version"]`.

**Acceptance**: All missing dependencies are reported in one error before any step runs. Available dependencies produce no output.

---

## Deliverable 6 — Step Executor

**Goal**: Execute steps in order, applying conditions, env merging, workdir, soft-fail, and producing correct output.

### Tasks

1. **`executor.py` — `run_flow(flow: Flow, context: dict, dry_run: bool, single_step: str | None) -> int`**

   **`single_step` handling:**
   - If `single_step` is set, validate it against `flow.workflow.steps` first; if not found, print an error listing valid step names and exit 1
   - When valid, skip the dependency check but still run all pre-flight argument and template checks
   - Filter the step list to only that step; the step counter shows the step's original position in the full flow (e.g. `[2/3]` not `[1/1]`), giving orientation within the larger workflow

   **For each step in list order:**
   - Print step header: `[{original_index}/{total}] {step.name} — {step.description}`
   - Evaluate `condition` via `evaluate_condition`; if falsy, print grey "skipped" line and continue
   - Render `command` via `render_command`
   - Resolve `workdir` via `render_command` if set (it may contain template vars)
   - Merge env: `{**os.environ, **flow.workflow.env, **step.env}` (step-level wins on conflict)
   - If `dry_run`: print the rendered command and continue without executing
   - Otherwise: execute via `subprocess.run(command, shell=True, cwd=workdir, env=merged_env)` with **no stdout/stderr capture** — output streams directly to the terminal in real time
   - On non-zero exit:
     - `soft_fail=False`: call `output.print_step_failure(name, exit_code)` (exit code only; stdout/stderr are already on screen above); return that exit code immediately
     - `soft_fail=True`: call `output.print_soft_fail(name, exit_code)`; continue

2. **Exit summary**: After all steps complete (or after a hard failure), print counts: `"3 passed, 1 soft-failed, 1 skipped"`; return 0 if no hard failures

**Acceptance**: Steps run in order with real-time output. Soft-fail steps log warning and continue. Condition-false steps are grey. Hard failures print exit code, halt, and return non-zero. Dry-run prints rendered commands without executing. `--step nonexistent` exits 1 with a list of valid step names.

---

## Deliverable 7 — Output & Color Helpers

**Goal**: Centralize all terminal output so `--no-color` works globally and output is consistent.

### Tasks

1. **`output.py`** — thin wrapper around ANSI codes; reads a module-level `COLOR_ENABLED` flag

   ```python
   COLOR_ENABLED: bool = True  # Set once at startup by cli.main() based on --no-color

   def print_step_header(index: int, total: int, name: str, description: str | None): ...
   def print_step_success(name: str): ...
   def print_step_failure(name: str, exit_code: int): ...
   def print_soft_fail(name: str, exit_code: int): ...
   def print_step_skipped(name: str): ...
   def print_preflight_error(message: str): ...
   def print_summary(passed: int, soft_failed: int, skipped: int, failed: list[str]): ...
   ```

2. **Color mapping**:
   - Green: step succeeded
   - Yellow: soft-fail (ran, non-zero, continuing)
   - Grey/dim: skipped by condition
   - Red: hard failure

3. **`--no-color`**: `cli.main()` sets `output.COLOR_ENABLED = False` once before dispatching to any subcommand. Tests that need to assert on color-free output use `monkeypatch.setattr(output, "COLOR_ENABLED", False)`.

---

## Deliverable 8 — `validate`, `list`, `init` Subcommands

### Tasks

1. **`cli-flow validate <file>`**
   - Call `load_flow(file)`; on success print `"✓ valid"` and exit 0; on `SchemaError` print the error and exit 1
   - Does not require arguments to be provided (schema-only check)

2. **`cli-flow list <file>`**
   - Call `load_flow(file)`
   - Print a table: step index, name, description, condition (if set), soft-fail flag
   - Format:
     ```
     Steps in onboarding.yaml:
       1  pullRepo       Clone the repository
       2  startServices  Start Docker services
       3  showStatus     Show running containers   [soft-fail]
     ```

3. **`cli-flow init`**
   - Interactive scaffolder using `input()` prompts
   - Prompts: flow name, version, description, number of arguments, number of steps
   - Output filename: `{name.lower().replace(" ", "-")}.yaml` in the current directory
   - Does not overwrite an existing file without explicit confirmation (`y/N` prompt)

---

## Deliverable 9 — `compile` Subcommand

**Goal**: Produce a self-contained, executable artifact from a flow YAML file that can be shared and run without `cli-flow` installed or the YAML file present.

### What "compile" means

`cli-flow compile onboarding.yaml` produces `./onboarding` — a [Python zipapp](https://docs.python.org/3/library/zipapp.html) that:
- Bundles the flow YAML and the entire `cli_flow` runtime into a single file
- Is directly executable: `./onboarding --repo foo/bar --target ~/dev`
- Behaves identically to `cli-flow run onboarding.yaml --repo foo/bar --target ~/dev`
- Requires Python 3.11+ on the target machine; optionally zero other dependencies (see `--bundle-deps`)

### Tasks

1. **`compiler.py` — `compile_flow(flow_path: str, output_path: str, bundle_deps: bool) -> None`**
   - Validate the flow file first (call `load_flow`)
   - Use `tempfile.TemporaryDirectory()` as a context manager for all build work — automatically cleaned up on success or error, leaving no artifacts in the project directory
   - Inside the temp dir, build:
     ```
     _build/
     ├── __main__.py        # bootstrap: reads embedded flow.yaml and calls run_compiled
     ├── cli_flow/          # copy of the full cli_flow package
     └── flow.yaml          # copy of the input flow file
     ```
   - Call `zipapp.create_archive(source="_build", target=output_path, interpreter="/usr/bin/env python3")`
   - Set the output file as executable (`chmod +x`)

2. **CLI wiring in `cli.py`**
   ```
   cli-flow compile <file> [--output <path>] [--bundle-deps]
   ```
   - `--output`: default is the flow `name` field (lowercased, spaces → hyphens) in the current directory
   - `--bundle-deps`: vendor `PyYAML` and `Jinja2` into the zipapp so the artifact has zero runtime dependencies beyond Python 3.11+

3. **Embedded `__main__.py`** (written into the zipapp build dir, not the installed package)
   ```python
   import sys
   import importlib.resources
   from cli_flow.cli import run_compiled

   # Read the bundled flow YAML using importlib.resources, which works correctly
   # inside a zipapp where __file__ does not point to a real filesystem path
   flow_yaml = importlib.resources.read_text(".", "flow.yaml")
   run_compiled(flow_yaml, sys.argv[1:])
   ```
   - `run_compiled(flow_yaml_str: str, argv: list[str])` is a new function in `cli.py` that accepts the YAML content as a string (already read), parses it, and runs directly: parse args → pre-flight → execute — no subcommand routing

4. **`--bundle-deps` vendoring**
   - Run: `pip install --target=_build/vendor --no-binary :all: PyYAML Jinja2`
   - `--no-binary :all:` forces pure-Python wheels only, ensuring no `.so`/`.pyd` C extensions are included (C extensions cannot be loaded from inside a zipapp)
   - The embedded `__main__.py` prepends `vendor` to `sys.path` before importing `cli_flow`:
     ```python
     import sys, os
     sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
     ```
   - All YAML parsing throughout `cli_flow` uses `yaml.safe_load` (pure-Python `SafeLoader`) — never `yaml.load` with `CLoader` — so the pure-Python vendored PyYAML works correctly

5. **Compile output confirmation**
   ```
   Compiled: ./onboarding  (42 KB)
   Run with: ./onboarding --help
   ```

**Acceptance**:
- `cli-flow compile onboarding.yaml` produces `./onboarding` with no leftover build directories
- `./onboarding --help` prints the flow's help text
- `./onboarding --repo foo/bar --target ~/dev` runs all steps
- The original `onboarding.yaml` file is not required to be present at runtime
- With `--bundle-deps`, the artifact runs on a machine where only Python 3.11+ is installed

---

## Deliverable 10 — Tests

**Goal**: Every module has unit tests; the executor and compiler have integration tests against real fixture flows.

### Tasks

1. **`tests/fixtures/`** — create these YAML files:
   - `valid_full.yaml` — uses all schema features (all arg types, conditions, soft-fail, workdir, env)
   - `invalid_missing_name.yaml` — missing required top-level key
   - `invalid_enum_no_options.yaml` — enum type with no `options` field
   - `optional_no_default_referenced.yaml` — optional arg with no default used in a step command

2. **`test_loader.py`**: valid file → correct dataclasses; each invalid fixture → correct `SchemaError`; argument with no `default` key → `default is _MISSING`

3. **`test_arguments.py`**: correct type coercion for all four types; `--port 8080` → `8080` (int not float); required arg missing → exit 1; optional arg with `_MISSING` default referenced in template → `PreflightError`

4. **`test_template.py`**: all five template features; `StrictUndefined` raises on unknown var; JS-style ternary rewrite works; `||` in template raises Jinja2 syntax error; condition evaluation returns correct bool

5. **`test_dependencies.py`**: mock `subprocess.run`; available deps → no error; missing deps → `PreflightError` listing all missing

6. **`test_executor.py`**: mock `subprocess.run`; step success → green output; soft-fail step → yellow, continues; condition-false step → grey, skipped; hard-fail → halts, returns non-zero; dry-run → no subprocess calls; `--step nonexistent` → exit 1 with valid names listed; `--step valid` → shows original step position in counter

7. **`test_compiler.py`** *(integration)*: compile a fixture flow → output file exists, is executable, no `_build/` directory left behind; run the compiled artifact as a subprocess with `--help` → exit 0; run with valid args → exit 0

---

## Implementation Order

Deliverables 1–9 are sequential — each builds on the previous. Tests (Deliverable 10) are written **alongside** each deliverable as it is implemented, not deferred to the end. The implementation order reflects dependency, not a suggestion to defer testing.

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
        ↑ tests written in parallel with each step ↑
```

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CLI framework | `argparse` (stdlib) | No external dependency; sufficient for this use case |
| Template engine | Jinja2 | Mature, well-understood, handles all required expression types |
| Ternary syntax | Pre-process `A ? B : C` → Jinja2 `B if A else C` | Keeps YAML authoring syntax matching the PRD without a custom parser |
| Fallback syntax | Native Jinja2 `or` — authors write `{{ x or '.' }}` | `\|\|` is not rewritten; Jinja2 `or` is clear and unambiguous |
| Step schema | YAML list (not map) | Guarantees ordering; maps are semantically unordered |
| Template variable name | Same as argument key | Removes `variable` indirection; simpler authoring |
| Boolean CLI style | Flag presence = true | Idiomatic; `--useHttps` sets true, omission = false |
| `number` coercion | Try `int` first, fall back to `float` | `--port 8080` → `8080` not `8080.0`; floats still work |
| `default` sentinel | `_MISSING = object()` | Distinguishes "no default" from `default: null` |
| Optional arg + no default | Pre-flight error if referenced in template | Prevents silent empty-string bugs in shell commands |
| Template reference scan | Jinja2 AST (`env.parse` + walk `Name` nodes) | Handles all edge cases; regex cannot reliably parse template expressions |
| Step output | Stream to terminal in real time (`shell=True`, no PIPE) | Long-running commands give live feedback; failure summary shows exit code only |
| `COLOR_ENABLED` | Module-level flag set once in `main()`; tests use `monkeypatch` | No global mutation during tests; no config object threading |
| Dependency check method | Run `<dep> --version` and check exit code | Handles subcommands like `docker compose`; no PATH parsing required |
| YAML loader | `yaml.safe_load` / `SafeLoader` always | Pure-Python; required for zipapp compatibility |
| Compile build dir | `tempfile.TemporaryDirectory()` | Auto-cleaned on success or error; no project pollution |
| Compiled artifact file reading | `importlib.resources` | Correct inside zipapps where `__file__` is a virtual path |
| `--bundle-deps` C extension exclusion | `pip install --no-binary :all:` | C extensions cannot be loaded from inside a zipapp |
| Compile format | Python zipapp (`.pyz`) | Stdlib support, single file, directly executable, no build tools needed |
| Condition color | Grey (separate from yellow soft-fail) | Visual distinction between intentional skip and soft failure |
| `--step` counter | Shows original position (e.g. `[2/3]`) | Orients the user within the full flow when debugging a single step |
