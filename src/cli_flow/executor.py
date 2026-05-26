"""Step execution loop.

Runs flow steps in order, handling:
- condition evaluation (skip if falsy)
- template rendering for command and workdir
- environment variable merging
- real-time output streaming (no capture)
- soft-fail vs hard-fail
- dry-run mode
- single-step targeting
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from cli_flow import output
from cli_flow.errors import PreflightError
from cli_flow.loader import Flow, Step
from cli_flow.template import evaluate_condition, render_command


def run_flow(
    flow: Flow,
    context: dict[str, Any],
    dry_run: bool,
    single_step: str | None,
) -> int:
    """Execute the flow's steps and return an exit code (0 = success).

    If single_step is set, only that step is run. The step's original
    position in the full list is shown in the progress counter.
    """
    steps = flow.workflow.steps
    total = len(steps)

    if single_step is not None:
        step_names = [s.name for s in steps]
        if single_step not in step_names:
            output.print_preflight_error(
                f"No step named '{single_step}'. "
                f"Valid steps: {', '.join(step_names)}"
            )
            return 1
        # Filter to just the requested step, but keep its original 1-based index
        steps_to_run = [
            (i + 1, s) for i, s in enumerate(steps) if s.name == single_step
        ]
    else:
        steps_to_run = [(i + 1, s) for i, s in enumerate(steps)]

    passed = 0
    soft_failed = 0
    skipped = 0
    failed: list[str] = []

    for index, step in steps_to_run:
        output.print_step_header(index, total, step.name, step.description)

        # --- condition check ---
        if step.condition is not None:
            try:
                should_run = evaluate_condition(step.condition, context)
            except PreflightError as exc:
                output.print_preflight_error(str(exc))
                return 1
            if not should_run:
                output.print_step_skipped(step.name)
                skipped += 1
                continue

        # --- render command and workdir ---
        try:
            cmd = render_command(step.command, context)
            cwd = render_command(step.workdir, context) if step.workdir else None
        except PreflightError as exc:
            output.print_preflight_error(str(exc))
            return 1

        # --- dry-run: print and skip execution ---
        if dry_run:
            print(f"  $ {cmd}")
            if step.result:
                context[step.result] = "<captured>"
            if step.error:
                context[step.error] = "<captured>"
            continue

        # --- execute ---
        exit_code, captured_out, captured_err = _run_step(cmd, cwd, flow, step)

        if exit_code == 0:
            if step.result is not None:
                context[step.result] = captured_out or ""
            if step.error is not None:
                context[step.error] = captured_err or ""
            output.print_step_success(step.name)
            passed += 1
        elif step.soft_fail:
            output.print_soft_fail(step.name, exit_code)
            soft_failed += 1
        else:
            output.print_step_failure(step.name, exit_code)
            failed.append(step.name)
            output.print_summary(passed, soft_failed, skipped, failed)
            return exit_code

    output.print_summary(passed, soft_failed, skipped, failed)
    return 0 if not failed else 1


def _run_step(
    cmd: str, cwd: str | None, flow: Flow, step: Step
) -> tuple[int, str | None, str | None]:
    """Execute a single step command.

    Returns (exit_code, captured_stdout, captured_stderr). Streams that are not
    captured are None; streams that are captured are printed then returned as
    stripped strings.
    """
    merged_env = {**os.environ, **flow.workflow.env, **step.env}

    stdout_pipe = subprocess.PIPE if step.result is not None else None
    stderr_pipe = subprocess.PIPE if step.error is not None else None

    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        env=merged_env,
        stdout=stdout_pipe,
        stderr=stderr_pipe,
    )

    captured_out: str | None = None
    captured_err: str | None = None

    if step.result is not None and result.stdout is not None:
        captured_out = result.stdout.decode(errors="replace").strip()
        if captured_out:
            print(captured_out)

    if step.error is not None and result.stderr is not None:
        captured_err = result.stderr.decode(errors="replace").strip()
        if captured_err:
            print(captured_err, file=__import__("sys").stderr)

    return result.returncode, captured_out, captured_err
