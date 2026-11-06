"""Blank the comments of the Python sources that go into the release wheel.

Run in the publish job only, on the CI checkout, right before ``python -m build
--wheel``. The comments are about an eighth of the compressed wheel and nothing
reads them at runtime: the AST, docstrings (FastAPI descriptions), string
literals and line numbers all stay exactly as they were, so a traceback from an
installed server still points at the right line of the repository source.

Kept on purpose: the leading header block of every file (licence and copyright
lines, shebang, encoding cookie) and any comment carrying a zero-width
character, which is the provenance mark and must survive into what ships.

Usage: python scripts/strip_wheel_comments.py backend/app backend/alembic
"""

from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

MARKS = ("​", "‌", "‍", "⁠")


def strip_source(source: str) -> str:
    """Return ``source`` with comments removed and every line number unchanged."""
    lines = source.splitlines(keepends=True)
    cuts: dict[int, int] = {}
    seen_code = False
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            if not seen_code or any(m in tok.string for m in MARKS):
                continue
            cuts[tok.start[0] - 1] = tok.start[1]
        elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING, tokenize.INDENT, tokenize.DEDENT):
            seen_code = True
    for row, col in cuts.items():
        line = lines[row]
        ending = line[len(line.rstrip("\r\n")) :]
        lines[row] = line[:col].rstrip() + ending
    return "".join(lines)


def main(roots: list[str]) -> int:
    if not roots:
        print("usage: strip_wheel_comments.py <dir> [<dir> ...]", file=sys.stderr)
        return 2
    files = before = after = 0
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            new = strip_source(text)
            if new != text:
                path.write_bytes(new.encode("utf-8"))
                files += 1
            before += len(raw)
            after += len(new.encode("utf-8"))
    print(f"stripped comments from {files} files: {before / 1048576:.1f} MiB -> {after / 1048576:.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
