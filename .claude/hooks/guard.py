"""PreToolUse hook: block access to .env secrets and destructive git commands.

Exit code 2 blocks the tool call and shows stderr to Claude.
"""

import json
import re
import sys

# .env, .ENV, .env.local, .env.example.bak ... (Windows paths are case-insensitive).
# Only the exact name .env.example is allowed.
ENV_FILE = re.compile(r"(?<![\w-])\.env(?P<suffix>(?:\.[\w-]+)*)(?![a-zA-Z0-9])", re.IGNORECASE)
# Glob tricks like .e[n]v or .en? that would still match a secrets file.
GLOB_TRICK = re.compile(r"\.e(n)?[\[\]?*{]", re.IGNORECASE)
GLOB_META = re.compile(r"[\[\]?{}]")

# [^;&|\n]* keeps each match inside one shell command segment.
SEG = r"[^;&|\n]*"
DANGEROUS_GIT = [
    re.compile(
        rf"\bgit\b{SEG}\bpush\b{SEG}(\s--force(-with-lease)?\b|\s-\w*f\w*\b|\s\+\S|\s--mirror\b)",
        re.IGNORECASE,
    ),
    re.compile(rf"\bgit\b{SEG}\breset\b{SEG}\s--hard\b", re.IGNORECASE),
    re.compile(rf"\bgit\b{SEG}\bclean\b{SEG}(\s-\w*f\w*\b|\s--force\b)", re.IGNORECASE),
]
LINE_CONTINUATION = re.compile(r"[\\`]\r?\n")


def touches_secret(text: str) -> bool:
    return any(m.group("suffix").lower() != ".example" for m in ENV_FILE.finditer(text))


def glob_touches_secret(pattern: str) -> bool:
    return bool(GLOB_TRICK.search(pattern)) or touches_secret(GLOB_META.sub("", pattern))


def block(reason: str) -> None:
    print(f"Blocked by .claude/hooks/guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input")
    if not isinstance(inp, dict):
        return

    if tool in ("Read", "Edit", "Write", "NotebookEdit", "Grep", "Glob"):
        paths = ("file_path", "notebook_path", "path")
        globs = ("glob",) + (("pattern",) if tool == "Glob" else ())
        if any(touches_secret(str(inp.get(f) or "")) for f in paths) or any(
            glob_touches_secret(str(inp.get(f) or "")) for f in globs
        ):
            block("secrets file (.env) is off-limits; edit .env.example instead.")

    if tool in ("Bash", "PowerShell"):
        cmd = LINE_CONTINUATION.sub(" ", str(inp.get("command") or ""))
        if touches_secret(cmd):
            block("command touches a .env secrets file.")
        for pat in DANGEROUS_GIT:
            if pat.search(cmd):
                block("destructive git command; ask the user to run it themselves.")


if __name__ == "__main__":
    main()
