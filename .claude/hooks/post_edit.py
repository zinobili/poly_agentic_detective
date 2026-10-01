"""PostToolUse hook: ruff-format and ruff-fix any .py file Claude just edited.

Reads the hook payload on stdin. Never blocks: lint problems that ruff can't
auto-fix are fed back to Claude as context so it can fix them.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUFF = ROOT / ".venv" / "Scripts" / "ruff.exe"
if not RUFF.exists():
    RUFF = ROOT / ".venv" / "bin" / "ruff"
if not RUFF.exists() and shutil.which("ruff"):
    RUFF = Path(shutil.which("ruff"))  # e.g. CI, where ruff is installed on PATH


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return
    path = payload["tool_input"].get("file_path") or ""
    if not path.endswith(".py") or not RUFF.exists():
        return
    if ROOT not in Path(path).resolve().parents or ".venv" in Path(path).parts:
        return
    subprocess.run([str(RUFF), "format", "--quiet", path], cwd=ROOT, check=False)
    # F401 unfixable: don't delete an import added one edit before its first use.
    check = subprocess.run(
        [str(RUFF), "check", "--fix", "--unfixable", "F401", "--quiet", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0 and check.stdout.strip():
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "ruff found issues:\n" + check.stdout[:2000],
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
