"""Tests for the Claude Code harness hooks in .claude/hooks/."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"
POST_EDIT = ROOT / ".claude" / "hooks" / "post_edit.py"
SECRET = "." + "env"  # built at runtime so this file's own commands don't trip the guard


def run_guard(tool: str, **tool_input) -> int:
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(GUARD)], input=payload, text=True, capture_output=True
    ).returncode


@pytest.mark.parametrize(
    "tool, field, value, blocked",
    [
        ("Read", "file_path", f"C:/repo/{SECRET}", True),
        ("Read", "file_path", f"C:/repo/{SECRET}.local", True),
        ("Edit", "file_path", f"/repo/{SECRET}", True),
        ("Read", "file_path", f"C:/repo/{SECRET}.example", False),
        ("Read", "file_path", "C:/repo/src/poly_actor/config.py", False),
        ("Read", "file_path", "C:/repo/.venv/lib/site.py", False),
        ("Bash", "command", f"cat {SECRET}", True),
        ("Bash", "command", f"type {SECRET}.local", True),
        ("Bash", "command", f"cp {SECRET}.example notes.txt", False),
        ("Bash", "command", "python -c 'from dotenv import load_dotenv'", False),
        ("Bash", "command", "git push --force origin main", True),
        ("Bash", "command", "git push -f origin main", True),
        ("Bash", "command", "git reset --hard HEAD~1", True),
        ("Bash", "command", "git clean -fd", True),
        ("Bash", "command", "git push origin main", False),
        ("PowerShell", "command", f"Get-Content {SECRET}", True),
        ("Bash", "command", "ls -la", False),
        # case-insensitive (Windows)
        ("Read", "file_path", f"C:/repo/{SECRET.upper()}", True),
        ("PowerShell", "command", f"Get-Content {SECRET.upper()}", True),
        # Grep / Glob
        ("Grep", "path", f"C:/repo/{SECRET}", True),
        ("Glob", "glob", f"**/{SECRET}*", True),
        ("Grep", "path", "C:/repo/src", False),
        # tight boundaries
        ("Bash", "command", f"cat {SECRET}>out", True),
        ("Bash", "command", f"cat <{SECRET}", True),
        ("Bash", "command", f"cat {SECRET}*", True),
        ("Bash", "command", f"cp {SECRET}.example.bak x", True),
        ("Bash", "command", f"cat {SECRET}.example-old", True),
        ("Bash", "command", "ls .venv/Scripts", False),
        ("Bash", "command", "cat .envrc environment.yml", False),
        # more destructive git forms
        ("Bash", "command", "git push origin +main", True),
        ("Bash", "command", "git push -fu origin main", True),
        ("Bash", "command", "git -C . push -f", True),
        ("Bash", "command", "git -c x=y push --force", True),
        ("Bash", "command", "git push --mirror", True),
        ("Bash", "command", "git reset HEAD --hard", True),
        ("Bash", "command", "git clean --force", True),
        ("Bash", "command", "git push origin main && echo -f", False),
        ("Bash", "command", "git push --follow-tags origin main", False),
        ("Bash", "command", "git reset --soft HEAD~1", False),
        # round-2 validator findings
        ("Bash", "command", f"cat {SECRET}_prod", True),
        ("Grep", "glob", ".e[n]v", True),
        ("Grep", "glob", "**/.en?", True),
        ("Glob", "pattern", "**/.[e]nv*", True),
        ("Glob", "pattern", "**/*.py", False),
        ("Grep", "glob", "*.py", False),
        ("Bash", "command", "GIT push -f origin main", True),
        ("PowerShell", "command", "Git reset --hard", True),
        ("Bash", "command", "git push origin main \\\n  --force", True),
        ("PowerShell", "command", "git push origin main `\n  --force", True),
    ],
)
def test_guard(tool, field, value, blocked):
    assert (run_guard(tool, **{field: value}) == 2) is blocked


@pytest.mark.parametrize(
    "raw", ["not json", "null", "[]", '{"tool_name":"Bash","tool_input":null}']
)
def test_hooks_tolerate_odd_payloads(raw):
    for hook in (GUARD, POST_EDIT):
        r = subprocess.run([sys.executable, str(hook)], input=raw, text=True)
        assert r.returncode == 0


def test_post_edit_formats_repo_file_and_keeps_unused_import(tmp_path):
    target = ROOT / "tests" / "_hook_tmp.py"
    target.write_text("import os\nx = {  'a':1 }\n")
    try:
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
        subprocess.run([sys.executable, str(POST_EDIT)], input=payload, text=True, check=True)
        assert target.read_text() == 'import os\n\nx = {"a": 1}\n'
    finally:
        target.unlink()


def test_post_edit_ignores_files_outside_repo(tmp_path):
    outside = tmp_path / "scratch.py"
    outside.write_text("x = {  'a':1 }\n")
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(outside)}})
    subprocess.run([sys.executable, str(POST_EDIT)], input=payload, text=True, check=True)
    assert outside.read_text() == "x = {  'a':1 }\n"
