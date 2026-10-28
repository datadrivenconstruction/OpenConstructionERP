#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Keep the requirements import sample a row the importer would actually accept.

`requirements.import_placeholder` is the greyed-out example under the paste box
on the requirements import panel. A user reads it to learn the row format and
copies its shape. Seven pipe-separated fields, and the format line above it
names them:

    entity | attribute | constraint_type | value | unit | category | priority

Four of those are free text and translating them helps: entity, attribute, the
value and its unit, and category, which the backend stores as an unconstrained
string. Two are closed vocabularies the importer matches literally, and
translating them is what this gate is for.

    constraint_type -> OPERATORS in backend/app/modules/requirements/evaluator.py
    priority        -> PRIORITY_ORDER in backend/app/modules/requirements/intl.py
                       plus the legacy spelling in requirements/schemas.py

Measured 2026-09-01, before this gate existed: 36 of the 42 locale files shipped
a sample row the importer rejects. Every one of them had translated `must`, so
`RequirementCreate` raises a ValidationError on the priority pattern and the row
never lands. Ten had also translated the operator - `мин`, `ελάχ`, `доод`,
`সর্বনিম্ন`, `حداقل`, `מינימום`, `maks` - which is quieter and worse: the
operator falls out of OPERATORS, the parser warns and silently substitutes
`equals`, and a minimum thickness of 200 becomes a requirement that the
thickness *equal* 200.

The six files that were correct were the six nobody had translated: en, and the
five that still carried the English string verbatim. That is the shape of this
defect. It is not a missing translation, it is a translation that should never
have been made, so a gate that only looks for untranslated strings scores it
exactly backwards.

The vocabularies are read out of the backend sources with `ast`, not imported
and not copied, so this gate cannot drift away from the code it is checking. If
someone adds an operator or a MoSCoW level, this gate learns it on the next run.

Usage::

    python scripts/check_locale_requirement_sample.py

Exit code 0 means every locale's sample row would import. Exit code 1 means at
least one would not, and the output names the locale, the field and the value.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "frontend" / "src" / "app" / "locales"
REQUIREMENTS = REPO_ROOT / "backend" / "app" / "modules" / "requirements"

KEY = "requirements.import_placeholder"

#: The sample is a two-line string, and `\n` between them is an escape in the
#: TypeScript source, so it reaches us as these two characters, not a newline.
ROW_SEPARATOR = "\\" + "n"

#: Index of each field in the row, from the format line the panel shows.
CONSTRAINT_TYPE = 2
PRIORITY = 6
FIELD_COUNT = 7

_ENTRY = re.compile(r'^\s*"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', re.M)


def _assigned_strings(source: Path, name: str) -> list[str]:
    """Return the string literals assigned to `name` at module level."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value
        if value is None:
            continue
        if isinstance(value, ast.Call) and value.args:  # e.g. Final[...](...) wrappers
            value = value.args[0]
        if isinstance(value, ast.Tuple | ast.List | ast.Set):
            out = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if out:
                return out
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return [value.value]
    raise SystemExit(f"{source.name}: could not read {name}; this gate needs updating")


def vocabularies() -> tuple[set[str], set[str]]:
    operators = set(_assigned_strings(REQUIREMENTS / "evaluator.py", "OPERATORS"))
    priorities = set(_assigned_strings(REQUIREMENTS / "intl.py", "PRIORITY_ORDER"))
    priorities.update(_assigned_strings(REQUIREMENTS / "schemas.py", "LEGACY_PRIORITY"))
    return operators, priorities


def sample_rows(path: Path) -> str | None:
    for match in _ENTRY.finditer(path.read_text(encoding="utf-8")):
        if match.group(1) == KEY:
            return match.group(2)
    return None


def main() -> int:
    operators, priorities = vocabularies()
    if not operators or not priorities:
        print("could not read the backend vocabularies", file=sys.stderr)
        return 1

    failures: list[str] = []
    checked = 0
    for path in sorted(LOCALES_DIR.glob("*.ts")):
        value = sample_rows(path)
        if value is None:
            continue
        checked += 1
        for number, line in enumerate(value.split(ROW_SEPARATOR), start=1):
            fields = [cell.strip() for cell in line.split("|")]
            if len(fields) != FIELD_COUNT:
                failures.append(f"{path.stem}: row {number} has {len(fields)} fields, expected {FIELD_COUNT}")
                continue
            if fields[CONSTRAINT_TYPE].lower() not in operators:
                failures.append(
                    f"{path.stem}: row {number} constraint_type {fields[CONSTRAINT_TYPE]!r} "
                    f"is not an operator; the parser would warn and use 'equals' instead"
                )
            if fields[PRIORITY].lower() not in priorities:
                failures.append(
                    f"{path.stem}: row {number} priority {fields[PRIORITY]!r} "
                    f"is not a MoSCoW level; RequirementCreate would reject the row"
                )

    if failures:
        print(
            f"requirements import sample: {len(failures)} problem(s) across {checked} locales\n",
            file=sys.stderr,
        )
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print(
            f"\nOperators the importer accepts: {', '.join(sorted(operators))}"
            f"\nPriorities it accepts:          {', '.join(sorted(priorities))}"
            "\n\nTranslate the entity, attribute, value, unit and category in this sample. Leave the"
            "\nconstraint_type and priority alone - they are matched literally, and a translated one"
            "\nteaches the user a row shape that will not import.",
            file=sys.stderr,
        )
        return 1

    print(
        f"requirements import sample OK: {checked} locales, every row uses a real operator "
        f"({len(operators)} known) and a real priority ({len(priorities)} known)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
