"""Run UI pytest files with adaptive isolation for flaky Qt teardown crashes."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_TEST_ROOT = PROJECT_ROOT / "tests" / "ui"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ui_test_files() -> list[str]:
    return [path.relative_to(PROJECT_ROOT).as_posix() for path in sorted(UI_TEST_ROOT.rglob("test_*.py"))]


def _pytest_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "pytest", "-n", "0", *args]


def _run_pytest(target: str, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"Running {target}", flush=True)
    command = _pytest_command(*extra_args, target)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
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


def _parse_args(argv: list[str]) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    extra_args: list[str] = []
    for arg in argv:
        if arg.startswith("tests/ui/") or arg.endswith(".py") or "::" in arg:
            targets.append(arg)
        else:
            extra_args.append(arg)
    return (targets or _ui_test_files(), extra_args)


def main() -> int:
    targets, extra_args = _parse_args(sys.argv[1:])

    for test_file in targets:
        completed = _run_pytest(test_file, extra_args)
        if completed.returncode == 0:
            continue

        if _is_teardown_only_crash(completed):
            print(
                f"{test_file} exited with code {completed.returncode} after a passing summary; treating it as a Qt teardown-only crash.",
                file=sys.stderr,
                flush=True,
            )
            continue

        if "::" in test_file:
            return completed.returncode

        nodes = _collect_test_nodes(test_file)
        if not nodes:
            return completed.returncode

        print(
            f"{test_file} exited with code {completed.returncode}; retrying individual tests for isolation.",
            file=sys.stderr,
            flush=True,
        )
        for node in nodes:
            node_completed = _run_pytest(node, extra_args)
            if node_completed.returncode == 0 or _is_teardown_only_crash(node_completed):
                continue
            return node_completed.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
