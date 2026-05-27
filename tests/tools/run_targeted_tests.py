"""Reusable targeted test runner.

Usage examples:
  PYTHONPATH=backend .venv/bin/python tests/tools/run_targeted_tests.py
  PYTHONPATH=backend .venv/bin/python tests/tools/run_targeted_tests.py tests/test_chat_service.py tests/test_self_learning.py
"""

import subprocess
import sys

DEFAULT_TESTS = [
    "tests/test_chat_service.py",
    "tests/test_query_analyzer.py",
    "tests/test_self_learning.py",
    "tests/test_admin_maintenance.py",
]


def main() -> int:
    test_paths = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TESTS
    cmd = [sys.executable, "-m", "pytest", *test_paths, "-q"]

    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
