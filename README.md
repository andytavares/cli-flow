# cli-flow

A YAML-driven CLI orchestrator for defining, sharing, and executing repeatable command-line workflows.

Instead of maintaining fragile shell scripts or wiki pages with manual steps, write a declarative YAML flow file. `cli-flow` handles argument parsing, validation, template rendering, dependency checks, and execution — all with consistent, colored output.

---

## Table of Contents

- [Why cli-flow](#why-cli-flow)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Flow File Reference](#flow-file-reference)
  - [Top-level keys](#top-level-keys)
  - [Arguments](#arguments)
  - [Workflow](#workflow)
  - [Steps](#steps)
  - [Template syntax](#template-syntax)
- [CLI Commands](#cli-commands)
  - [run](#run)
  - [validate](#validate)
  - [list](#list)
  - [init](#init)
  - [compile](#compile)
- [Global Flags](#global-flags)
- [Example Flow](#example-flow)
- [Development](#development)
  - [Setup](#setup)
  - [Project Structure](#project-structure)
  - [Running Tests](#running-tests)
  - [Contributing](#contributing)

---

## Why cli-flow

- **Eliminate toil**: Replace multi-step runbooks with a single `cli-flow run` command.
- **Self-documenting**: Flow files live in version control alongside the code they operate on.
- **Consistent UX**: Every workflow gets argument validation, `--help`, dry-run, and colored output for free.
- **Portable**: Works on macOS, Linux, and Windows (WSL). Flows can be compiled into standalone executables that need no installed dependencies.

---

## Installation

Requires Python 3.11+.

```bash
pip install cli-flow
```

Or install from source:

```bash
git clone https://github.com/andytavares/cli-flow.git
cd cli-flow
pip install .
```

Verify:

```bash
cli-flow --help
```

---

## Quick Start

**1. Create a flow file** (`deploy.yaml`):

```yaml
name: "Deploy App"
version: "1.0.0"
description: "Build and deploy to a target environment"

arguments:
  env:
    type: enum
    description: "Target environment"
    required: true
    options: [staging, production]
  tag:
    type: string
    description: "Docker image tag to deploy"
    required: true

workflow:
  dependsOn:
    - docker
    - kubectl
  steps:
    - name: build
      description: "Build the Docker image"
      command: "docker build -t myapp:{{ tag }} ."
    - name: push
      description: "Push image to registry"
      command: "docker push myapp:{{ tag }}"
    - name: deploy
      description: "Apply Kubernetes manifests"
      command: "kubectl apply -f k8s/{{ env }}/"
```

**2. Validate the file:**

```bash
cli-flow validate deploy.yaml
```

**3. Preview the commands (dry run):**

```bash
cli-flow run deploy.yaml --env staging --tag v1.2.3 --dry-run
```

**4. Run it:**

```bash
cli-flow run deploy.yaml --env staging --tag v1.2.3
```

---

## Flow File Reference

### Top-level keys

| Key | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Display name used in help output and compiled artifact names |
| `version` | string | yes | Semantic version string |
| `description` | string | yes | Short description shown in help |
| `arguments` | map | no | Named input arguments (see below) |
| `workflow` | map | yes | Steps to execute (see below) |

### Arguments

Each argument is a named key under `arguments:`.

```yaml
arguments:
  myArg:
    type: string          # string | boolean | number | enum
    description: "..."    # Shown in --help output
    required: true        # true = must be provided; false = optional
    default: "value"      # Only allowed when required: false
    format: "example"     # Optional hint shown in --help (display only)
    options:              # Required when type: enum
      - optionA
      - optionB
```

**Types:**

| Type | CLI value examples | Notes |
|---|---|---|
| `string` | `--arg value` | Any string |
| `boolean` | `--arg true` / `--arg false` | Accepts `true`/`false` (case-insensitive) |
| `number` | `--arg 42` | Parsed as float |
| `enum` | `--arg optionA` | Must match one of `options` |

### Workflow

```yaml
workflow:
  dependsOn:            # List of executables that must exist on PATH before running
    - git
    - docker compose    # Space-separated commands are checked as a unit
  env:                  # Environment variables injected into every step
    MY_VAR: value
  steps:
    - ...
```

All missing dependencies are reported together before any step runs.

### Steps

```yaml
steps:
  - name: stepName          # Unique identifier (required)
    description: "..."      # Shown in `cli-flow list` and progress output (optional)
    command: "..."          # Shell command; supports {{ }} templates (required)
    workdir: "..."          # Working directory; supports {{ }} templates (optional)
    soft-fail: false        # If true, a non-zero exit continues execution (default: false)
    condition: "{{ ... }}"  # Skip this step if the expression is falsy (optional)
    result: varName         # Capture stdout into a variable for downstream steps (optional)
    error: varName          # Capture stderr into a variable for downstream steps (optional)
    env:                    # Step-level env vars; merged with workflow env (step wins)
      KEY: value
```

### Template syntax

Commands, `workdir`, and `condition` fields support [Jinja2](https://jinja.palletsprojects.com/) templates using `{{ }}` delimiters. All argument values are available by name.

```yaml
command: "git clone {{ repo }}.git {{ target }}"
condition: "{{ env == 'production' }}"
workdir: "{{ target }}/subdir"
```

**Ternary shorthand** (JavaScript-style) is also supported:

```yaml
# Equivalent to: {{ 'https://' if useHttps else 'git@' }}
command: "git clone {{ useHttps ? 'https://' : 'git@' }}github.com/{{ repo }}"
```

**Step output capture** — use `result` and `error` to store a step's stdout or stderr in a named variable. The variable is then available to all subsequent steps via `{{ }}` templates:

```yaml
steps:
  - name: getVersion
    command: git describe --tags --abbrev=0
    result: version          # stdout → {{ version }}
    error: versionErr        # stderr → {{ versionErr }}

  - name: buildImage
    command: docker build -t myapp:{{ version }} .
    condition: "{{ versionErr == '' }}"
```

Captured output is stripped of leading and trailing whitespace. The captured stream is still printed to the terminal so it remains visible.

Referencing an undefined variable is a hard error — there are no silent blanks.

---

## CLI Commands

### run

Execute a flow file.

```bash
cli-flow run <file> [--<arg> <value>...] [flags]
```

**Flags:**

| Flag | Description |
|---|---|
| `--dry-run` | Print rendered commands without executing them |
| `--step <name>` | Run only the named step (skips dependency check) |
| `--var key=value` | Override a variable (repeatable) |

**Examples:**

```bash
# Basic run
cli-flow run onboarding.yaml --repo mycompany/backend --target ~/dev

# Dry run to preview commands
cli-flow run onboarding.yaml --repo mycompany/backend --target ~/dev --dry-run

# Run a single step
cli-flow run onboarding.yaml --repo mycompany/backend --target ~/dev --step pullRepo
```

When `--step` is used, the progress counter reflects the step's original position (e.g. `[2/3]`) so output remains consistent with full runs.

### validate

Check the flow file against the schema without executing anything.

```bash
cli-flow validate <file>
```

Exits with a non-zero code and a descriptive error if the file is invalid.

### list

Print all steps with their names and descriptions.

```bash
cli-flow list <file>
```

Example output:

```
Developer Onboarding v1.0.0
Clone a repo and start local services

Steps:
  pullRepo        Clone the repository
  startServices   Start Docker services
  showStatus      Show running containers
```

### init

Interactively scaffold a new flow file.

```bash
cli-flow init
```

Prompts for a name, description, and step names, then writes a starter YAML file.

### compile

Bundle a flow into a standalone Python zipapp (`.pyz`) that can be run without `cli-flow` installed.

```bash
cli-flow compile <file> [--output <path>] [--bundle-deps]
```

| Flag | Description |
|---|---|
| `--output <path>` | Output path (default: flow name, lowercased, in current directory) |
| `--bundle-deps` | Vendor PyYAML and Jinja2 into the artifact (pure-Python only) |

```bash
# Compile
cli-flow compile onboarding.yaml --output ./onboarding --bundle-deps

# Run the compiled artifact (requires only Python 3.11+)
./onboarding --repo mycompany/backend --target ~/dev
```

---

## Global Flags

Available on all subcommands:

| Flag | Description |
|---|---|
| `--no-color` | Disable ANSI color output |
| `--verbose` | Print each command before executing |

---

## Example Flow

A complete developer onboarding flow (`onboarding.yaml`):

```yaml
name: "Developer Onboarding"
version: "1.0.0"
description: "Clone a repo and start local services"

arguments:
  repo:
    type: string
    format: "company/my-repo"
    description: "The repository to set up"
    required: true
  useHttps:
    type: boolean
    description: "Use HTTPS instead of SSH to clone"
    required: false
    default: false
  target:
    type: string
    format: "/path/to/location"
    description: "The location to clone the repo into"
    required: true
  port:
    type: number
    description: "Port to expose"
    required: false
    default: 8080
  env:
    type: enum
    description: "Deployment environment"
    required: false
    default: "local"
    options:
      - local
      - staging
      - production

workflow:
  dependsOn:
    - docker compose
    - git
  env:
    LOG_LEVEL: info
  steps:
    - name: pullRepo
      description: "Clone the repository"
      command: "git clone {{ useHttps ? 'https://github.com/' : 'git@github.com:' }}{{ repo }}.git {{ target }}"
    - name: startServices
      description: "Start Docker services"
      command: "docker compose up -d"
      workdir: "{{ target }}"
      env:
        COMPOSE_PROJECT_NAME: myproject
    - name: showStatus
      description: "Show running containers"
      command: "docker compose ps"
      workdir: "{{ target }}"
      soft-fail: true
      condition: "{{ env == 'local' }}"
```

Usage:

```bash
cli-flow run onboarding.yaml --repo mycompany/backend --target ~/dev
cli-flow run onboarding.yaml --repo mycompany/backend --target ~/dev --useHttps true
```

---

## Development

### Setup

```bash
git clone https://github.com/andytavares/cli-flow.git
cd cli-flow
pip install -e ".[dev]"
```

This installs `cli-flow` in editable mode along with test dependencies (`pytest`, `pytest-cov`).

### Project Structure

```
cli-flow/
├── pyproject.toml          # Package metadata and dependencies
├── src/cli_flow/
│   ├── __main__.py         # Entry point
│   ├── cli.py              # Argument parsing and subcommand dispatch
│   ├── loader.py           # YAML loading and schema validation
│   ├── arguments.py        # Argument parsing, type coercion, validation
│   ├── template.py         # Jinja2 template rendering and ternary preprocessing
│   ├── dependencies.py     # Pre-flight dependency checks
│   ├── executor.py         # Step execution loop with real-time output streaming
│   ├── compiler.py         # Compile flows into standalone .pyz artifacts
│   ├── output.py           # ANSI color helpers and consistent output formatting
│   └── errors.py           # Shared exception types
└── tests/
    ├── fixtures/           # Sample YAML files used by tests
    ├── test_loader.py
    ├── test_arguments.py
    ├── test_template.py
    ├── test_dependencies.py
    ├── test_executor.py
    └── test_compiler.py
```

**Data flow:**

```
YAML file
   ↓ loader.py         → Flow dataclass tree
   ↓ arguments.py      → dict[str, Any] of resolved values
   ↓ template.py       → rendered commands / conditions
   ↓ executor.py       → subprocess.run(), real-time output streaming
```

### Running Tests

```bash
# Run all tests
pytest

# With coverage report
pytest --cov=cli_flow

# Run a specific test file
pytest tests/test_loader.py

# Verbose output
pytest -v
```

Tests are configured in `pyproject.toml` (`testpaths = ["tests"]`).

### Contributing

1. **Fork** the repository and create a branch from `main`.
2. **Write tests** for any new behavior. All existing tests must pass.
3. Keep changes focused — one feature or fix per PR.
4. **Run the full test suite** before opening a PR:
   ```bash
   pytest --cov=cli_flow
   ```
5. Open a pull request with a clear description of what changed and why.

**Key design principles to follow:**

- Pure Python only — no C extensions (ensures zipapp portability).
- Use `yaml.safe_load` exclusively, never `CLoader`.
- Subprocess output is streamed in real-time, never captured.
- Collect all validation errors before reporting, rather than failing at the first one.
- Template variables must be explicitly defined; silent blanks are not acceptable.
