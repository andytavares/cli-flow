# Product Requirements Document: cli-flow

## Overview

`cli-flow` is a YAML-driven CLI orchestrator that lets teams define, share, and run repeatable command-line workflows. Instead of maintaining shell scripts or wikis, teams describe their flows in a versioned YAML file and `cli-flow` handles argument parsing, dependency checking, template rendering, and step execution.

---

## Problem Statement

Teams repeatedly solve the same problems with fragile shell scripts or dense wiki pages:

- Onboarding a new developer requires running a sequence of commands in the right order
- Setting up a repo, spinning up local infra, running migrations, seeding data — all error-prone when done manually
- Scripts drift, aren't documented, and are hard to share across operating systems
- No consistent UX: different repos use different argument styles, help text is missing, errors are cryptic

`cli-flow` solves this by providing a declarative, consistent interface for any workflow that maps to shell commands.

---

## Goals

- **Simple authoring**: A developer with no programming experience can write a flow in YAML
- **Consistent UX**: Every flow gets argument parsing, validation, `--help`, and error output for free
- **Portable**: Flows run on macOS, Linux, and Windows (WSL)
- **Composable**: Flows can call other flows or reuse shared step libraries
- **Safe by default**: Dependency checks before execution; fail-fast with clear error messages

---

## Non-Goals

- Not a general-purpose scripting language (use shell/Python for that)
- Not a CI/CD system (no remote execution, scheduling, or parallelism in v1)
- Not a secrets manager (env var injection is supported but secret storage is out of scope)

---

## Schema

### Top-Level Structure

```yaml
name: string                  # Display name for the CLI tool
version: string               # Semver version of this flow definition
description: string           # Short description shown in --help

arguments: <ArgumentMap>      # Named input arguments
workflow: <Workflow>          # The steps to execute
```

### Arguments

Each argument is a named key under `arguments:`. The key becomes both the CLI flag name (e.g. `repo` → `--repo`) and the template variable name (e.g. `{{ repo }}`).

```yaml
arguments:
  <name>:
    type: string | boolean | number | enum   # Data type
    description: string                      # Help text
    required: boolean                        # Whether the argument must be provided
    default: <value>                         # Default value if not provided (only when required: false)
    format: string                           # Example value shown in --help (e.g. "company/my-repo")
    options: [string]                        # Allowed values (only for type: enum)
```

**Type semantics:**

| Type    | CLI input         | Template value     | Notes                                      |
|---------|-------------------|--------------------|--------------------------------------------|
| string  | `--repo foo/bar`  | `"foo/bar"`        |                                            |
| boolean | `--useHttps`      | `true` / `false`   | Flag presence = `true`; omission = `false` |
| number  | `--port 8080`     | `8080`             |                                            |
| enum    | `--env staging`   | `"staging"`        |                                            |

**Boolean arguments** are flag-style: including `--useHttps` sets the value to `true`; omitting it sets the value to `false` (or the specified `default`). There is no `--useHttps false` form — to default to `true`, set `default: true` and omit the flag to keep it.

**Optional arguments with no default**: If a `required: false` argument has no `default` and is not provided by the user, any template that references it causes a pre-flight error. Either provide a `default` or ensure the argument is only referenced inside a condition that guards against its absence.

**The `format` field** is documentation-only. It is displayed as an example value in `--help` output and does not enforce or validate the argument's format.

### Workflow

```yaml
workflow:
  dependsOn: [string]          # Executables that must be available before any step runs
  env: <map>                   # Environment variables injected into every step
  steps:
    - name: string             # Unique step identifier
      command: string          # Shell command template (supports {{ }} expressions)
      description: string      # Optional: shown during execution
      soft-fail: boolean       # If true, execution continues on non-zero exit (default: false)
      condition: string        # Optional: {{ }} template expression; step is skipped if falsy
      workdir: string          # Optional: working directory for this step
      env: <map>               # Optional: step-level env vars (merged with workflow-level; step wins on conflict)
```

**Steps are a YAML list** and execute in the order they appear. This guarantees ordering regardless of YAML parser behavior.

**`dependsOn` checks**: Each entry is verified by running the command with a no-op invocation (e.g. `docker compose --version`) and checking for a zero exit code. This supports both single binaries and subcommands (e.g. `docker compose`). All missing dependencies are reported together before any step runs.

---

## Template Syntax

Commands and `condition` fields use `{{ }}` for variable interpolation and expressions. The template variable name is the same as the argument key.

| Feature             | Example                                      |
|---------------------|----------------------------------------------|
| Variable reference  | `{{ repo }}`                                 |
| Ternary             | `{{ useHttps ? 'https://' : 'git@' }}`       |
| Fallback / default  | `{{ targetDirectory \|\| '.' }}`              |
| String concat       | `{{ 'https://github.com/' + repo }}`         |
| Comparison          | `{{ env == 'production' }}`                  |

The template engine is evaluated after argument parsing and before command execution. Unresolved variables — including optional arguments with no default that were not provided — cause a pre-flight error that identifies the step and variable name.

---

## Execution Model

```
cli-flow run <flow-file.yaml> [arguments]
```

1. **Parse & validate** the YAML schema
2. **Collect arguments**: parse CLI flags, apply defaults, validate required fields, enforce types
3. **Pre-flight check**: verify all template references are resolvable; fail with a specific error if any optional argument without a default is used in a template but was not provided
4. **Dependency check**: for each entry in `dependsOn`, run `<entry> --version` (or equivalent no-op); report all missing dependencies and exit 1 if any fail
5. **Execute steps** in list order:
   a. Evaluate `condition` — skip step if the `{{ }}` expression is falsy; print step as skipped (grey)
   b. Render `command` template with resolved variables
   c. Execute in a subprocess with merged env (workflow-level + step-level; step wins on conflict)
   d. On non-zero exit: if `soft-fail: false`, stop and print error (red) and exit 1; if `soft-fail: true`, log warning (yellow) and continue
6. **Exit**: 0 on success, non-zero with a summary of failed steps

---

## CLI Interface

### Commands

```
cli-flow run <file>              Run a flow file
cli-flow validate <file>         Validate a flow file without executing
cli-flow list <file>             List steps and their descriptions
cli-flow init                    Scaffold a new flow file interactively
```

### Flags

```
--dry-run                        Print rendered commands without executing
--step <name>                    Run a single named step (skips dependency check)
--var key=value                  Override a variable (can be used multiple times)
--no-color                       Disable colored output
--verbose                        Print each command before running it
```

### Help output (auto-generated from YAML)

```
Company CLI

Usage:
  cli-flow run onboarding.yaml [flags]

Arguments:
  --repo       string   The repository to set up (format: company/my-repo) [required]
  --target     string   The location to set the repo up in (format: /path/to/location) [required]
  --useHttps   bool     If true use https to pull the repository instead of ssh

Steps:
  pullRepo        Clone the repository
  docker-compose  Start local services
```

---

## Example Flow

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
    description: "If true, use HTTPS instead of SSH to clone"
    required: false
    default: false
  target:
    type: string
    format: "/path/to/location"
    description: "The location to clone the repo into"
    required: true

workflow:
  dependsOn:
    - docker compose
    - git
  steps:
    - name: pullRepo
      description: "Clone the repository"
      command: "git clone {{ useHttps ? 'https://github.com/' : 'git@github.com:' }}{{ repo }}.git {{ target }}"
      soft-fail: false
    - name: startServices
      description: "Start Docker services"
      command: "docker compose up -d"
      workdir: "{{ target }}"
      soft-fail: false
    - name: showStatus
      description: "Show running containers"
      command: "docker compose ps"
      workdir: "{{ target }}"
      soft-fail: true
```

---

## Output & UX

- Each step prints a header: `[1/3] pullRepo — Clone the repository`
- Commands are printed in `--verbose` mode
- Failures print the exit code, stdout, and stderr
- A final summary prints pass/fail/skip counts and failed step names
- Color output:
  - **Green**: step succeeded
  - **Yellow**: step ran but exited non-zero with `soft-fail: true` (execution continued)
  - **Grey**: step was skipped because its `condition` evaluated to falsy
  - **Red**: step failed and halted execution

---

## Error Handling

| Scenario                                          | Behavior                                                        |
|---------------------------------------------------|-----------------------------------------------------------------|
| Missing required argument                         | Pre-flight error; print usage and exit 1                        |
| Wrong argument type                               | Pre-flight error with expected vs. received type                |
| Optional arg with no default referenced in template | Pre-flight error identifying the step and variable name       |
| Dependency not available                          | Pre-flight error listing all missing dependencies               |
| Unresolvable template variable                    | Pre-flight error identifying the step and variable              |
| Step exits non-zero, `soft-fail: false`           | Halt execution; print step output (red) and exit 1             |
| Step exits non-zero, `soft-fail: true`            | Log warning (yellow); continue to next step                     |
| Step skipped by `condition`                       | Print step as skipped (grey); continue to next step             |

---

## v1 Scope

| Feature                        | v1  |
|--------------------------------|-----|
| YAML parsing & validation      | yes |
| Argument parsing & types       | yes |
| Template interpolation         | yes |
| Dependency (PATH) checks       | yes |
| Sequential step execution      | yes |
| `--dry-run`                    | yes |
| `--verbose`                    | yes |
| `soft-fail` per step           | yes |
| `condition` (step skip)        | yes |
| `workdir` per step             | yes |
| Step-level env vars            | yes |
| `cli-flow validate`            | yes |
| `cli-flow list`                | yes |
| Parallel step execution        | no  |
| Flow composition (call flows)  | no  |
| Interactive prompts            | no  |
| Remote flow registry           | no  |
| Windows (native, not WSL)      | no  |

---

## Open Questions

1. **Template engine**: Use an existing expression library (e.g. expr-lang in Go, Jinja2-style) or build a minimal one? Tradeoff: power vs. complexity.
2. **Flow composition**: Should steps be able to call other flow files in v1, or defer to v2?
3. **Interactive prompts**: Should missing required arguments trigger an interactive prompt rather than failing immediately?
4. **Distribution**: Single binary (Go/Rust recommended), npm package, or Homebrew tap?
5. **Config file**: Should `cli-flow` support a project-level config (e.g. `.cli-flow.yaml`) to set default flags or flow paths?
