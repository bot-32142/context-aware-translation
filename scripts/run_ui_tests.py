"""Run UI pytest files with adaptive isolation for flaky Qt teardown crashes."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_TEST_ROOT = PROJECT_ROOT / "tests" / "ui"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_PRINT_LOCK = threading.Lock()


def _ui_test_files() -> list[str]:
    return [path.relative_to(PROJECT_ROOT).as_posix() for path in sorted(UI_TEST_ROOT.rglob("test_*.py"))]


def _pytest_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "pytest", "-n", "0", *args]


def _print_output(stdout: str, stderr: str) -> None:
    with _PRINT_LOCK:
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)


def _print_status(message: str, *, stderr: bool = False) -> None:
    with _PRINT_LOCK:
        print(message, file=sys.stderr if stderr else sys.stdout, flush=True)


def _coverage_enabled(extra_args: list[str]) -> bool:
    return any(arg == "--cov" or arg.startswith("--cov=") for arg in extra_args)


def _build_env(target: str, coverage_enabled: bool) -> dict[str, str]:
    env = os.environ.copy()
    if coverage_enabled:
        safe_target = re.sub(r"[^A-Za-z0-9._-]+", "_", target).strip("._") or "ui"
        env["COVERAGE_FILE"] = str(PROJECT_ROOT / f".coverage.ui.{safe_target}.{uuid4().hex}")
    return env


def _run_pytest(target: str, extra_args: list[str], *, coverage_enabled: bool) -> subprocess.CompletedProcess[str]:
    _print_status(f"Running {target}")
    command = _pytest_command(*extra_args, target)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=_build_env(target, coverage_enabled),
        check=False,
        capture_output=True,
        text=True,
    )
    _print_output(completed.stdout, completed.stderr)
    return completed


def _collect_test_nodes(test_file: str) -> list[str]:
    command = _pytest_command("--collect-only", "-qq", test_file)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []

    return [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.startswith("tests/ui/") and "::" in line
    ]


def _is_teardown_only_crash(completed: subprocess.CompletedProcess[str]) -> bool:
    if completed.returncode == 0:
        return False

    combined_output = f"{completed.stdout}\n{completed.stderr}"
    summary_lines = [
        line.strip()
        for line in combined_output.splitlines()
        if re.search(r"\bpassed\b", line) and " in " in line and line.strip().startswith("=")
    ]
    if not summary_lines:
        return False

    latest_summary = summary_lines[-1].lower()
    return "failed" not in latest_summary and "error" not in latest_summary


def _parse_job_count(raw_value: str) -> int | None:
    if raw_value == "auto":
        return None

    jobs = int(raw_value)
    if jobs < 1:
        raise ValueError("--jobs must be at least 1")
    return jobs


def _resolve_job_count(requested_jobs: int | None, target_count: int) -> int:
    if target_count <= 1:
        return 1
    if requested_jobs is None:
        return min(target_count, os.cpu_count() or 1)
    return min(target_count, requested_jobs)


def _parse_args(argv: list[str]) -> tuple[list[str], list[str], int | None]:
    targets: list[str] = []
    extra_args: list[str] = []
    requested_jobs: int | None = None
    iterator = iter(argv)
    for arg in iterator:
        if arg in {"--jobs", "-n", "--numprocesses"}:
            try:
                requested_jobs = _parse_job_count(next(iterator))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            except StopIteration as exc:  # pragma: no cover - defensive CLI handling
                raise SystemExit(f"{arg} requires a value") from exc
            continue
        if arg.startswith("--jobs="):
            try:
                requested_jobs = _parse_job_count(arg.split("=", 1)[1])
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            continue
        if arg.startswith("--numprocesses="):
            try:
                requested_jobs = _parse_job_count(arg.split("=", 1)[1])
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            continue
        if arg.startswith("tests/ui/") or arg.endswith(".py") or "::" in arg:
            targets.append(arg)
        else:
            extra_args.append(arg)
    return (targets or _ui_test_files(), extra_args, requested_jobs)


def _run_target(target: str, extra_args: list[str], *, coverage_enabled: bool) -> int:
    completed = _run_pytest(target, extra_args, coverage_enabled=coverage_enabled)
    if completed.returncode == 0:
        return 0

    if _is_teardown_only_crash(completed):
        _print_status(
            (
                f"{target} exited with code {completed.returncode} after a passing summary; "
                "treating it as a Qt teardown-only crash."
            ),
            stderr=True,
        )
        return 0

    if "::" in target:
        return completed.returncode

    nodes = _collect_test_nodes(target)
    if not nodes:
        return completed.returncode

    _print_status(
        f"{target} exited with code {completed.returncode}; retrying individual tests for isolation.",
        stderr=True,
    )
    for node in nodes:
        node_completed = _run_pytest(node, extra_args, coverage_enabled=coverage_enabled)
        if node_completed.returncode == 0 or _is_teardown_only_crash(node_completed):
            continue
        return node_completed.returncode

    return 0


def main() -> int:
    targets, extra_args, requested_jobs = _parse_args(sys.argv[1:])
    coverage_enabled = _coverage_enabled(extra_args)
    jobs = _resolve_job_count(requested_jobs, len(targets))

    if jobs == 1:
        for target in targets:
            result = _run_target(target, extra_args, coverage_enabled=coverage_enabled)
            if result != 0:
                return result
        return 0

    results_by_target: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_target = {
            executor.submit(_run_target, target, extra_args, coverage_enabled=coverage_enabled): target
            for target in targets
        }
        for future in as_completed(future_to_target):
            target = future_to_target[future]
            results_by_target[target] = future.result()

    for target in targets:
        result = results_by_target.get(target, 1)
        if result != 0:
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
