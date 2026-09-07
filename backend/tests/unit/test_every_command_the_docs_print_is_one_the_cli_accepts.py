# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every command line our documentation prints must be one the CLI accepts.

A command line in a document is a claim: this program exists, it takes these
arguments, and typing it does what the surrounding paragraph says. Nothing
checked that claim, and it went wrong in the worst possible place.
``docs/INSTALL_LINUX.md`` answered the single most common first-run failure,
a busy port, with ``openconstructionerp --port 9090``. ``--port`` is declared
on the ``serve`` and ``doctor`` subparsers and nowhere else, so the top-level
parser answers ``exit 2`` and the one page a stuck reader reaches told them to
type something that cannot work. The same section offered
``OE_PORT=9090 openconstructionerp`` as a fallback; no code under
``backend/app`` reads ``OE_PORT`` at all, so that one starts on 8080 again and
says nothing.

The gate is built out of the real parser rather than a list of known flags.
``_build_parser`` is the same function ``main`` calls, and ``app.cli`` imports
only the standard library at module scope, so this costs nothing and cannot
drift from what ships.

Three details are load-bearing.

*Abbreviation.* ``allow_abbrev`` is on by default, so ``parse_args`` accepts
``--data DIR`` for ``--data-dir`` and a documented flag that no longer exists
under that spelling could pass on a prefix of a different one. Every long
option is therefore also required to appear verbatim in the ``option_strings``
of the parser the command line actually addresses.

*Population.* Every tracked Markdown file plus the published docs page, minus
two exclusions that are named here and printed by the test rather than
filtered away in silence. A gate whose population quietly shrinks reports
green for the wrong reason, so the count and the file list are printed beside
the verdict and a floor assertion names the pages a stuck user actually
reaches.

*Synopses.* ``backend/README.md`` documents ``serve [--host HOST] [--port
PORT] ...``. Fed to ``parse_args`` verbatim those reject on the brackets, and
skipping them would leave the one place in the docs whose entire purpose is
to list the flags unchecked. They are expanded instead, and each bracketed
option is checked against the real parser.

What this does NOT cover, so that nobody reads a green here as more than it
is: the runtime strings the CLI prints are f-strings carrying formatting
placeholders and decorative separators, and an extractor over them produces
false verdicts in both directions. The two hints that were wrong are covered
instead by executing the checks that print them, at the bottom of this file.
"""

from __future__ import annotations

import argparse
import html
import re
import shlex
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from app.cli import _build_parser, check_data_dir, check_port_free

# ── Population ────────────────────────────────────────────────────────────
# Every tracked Markdown file, plus the published docs page. Deliberately not
# a hand-picked list: the defect this test was written for lived in a file
# nobody would have thought to list.
DOC_PATTERNS = ("*.md", "docs/docs.html")

# Internal-only documents (CLAUDE.md restriction 9). These are gitignored, so
# `git ls-files` does not return them anyway; the prefixes are stated so the
# exclusion is a decision on the record rather than an accident of what
# happens to be tracked today.
INTERNAL = (
    "docs/strategy/",
    "docs/qa/",
    "docs/postgres-migration/",
    "docs/RUNBOOK.md",
    "docs/SECURITY_AUDIT",
    "qa/",
)

# Historical records. A release note describing the commands of its own
# release is correct as written even when those commands have since been
# renamed, and rewriting one would falsify the record. Including them would
# also make this gate permanently red for something nobody may fix.
HISTORICAL = ("CHANGELOG.md", "docs/release/", ".github/release-notes-")

# The pages a first-run reader actually lands on. If a future edit narrows the
# glob or moves a file, this turns the gate red instead of quietly green.
MUST_BE_COVERED = (
    "README.md",
    "backend/README.md",
    "docs/INSTALL_LINUX.md",
    "docs/docs.html",
    "docs/partner-packs/README.md",
)
MINIMUM_FILES = 100
MINIMUM_INVOCATIONS = 60

PROGRAM_NAMES = ("openconstructionerp", "openestimate")

# `python -m openconstructionerp ...`, the spelling the docs recommend when the
# console script is not on PATH. It reaches the same `main` through
# `backend/openconstructionerp/__main__.py`, so the same parser answers it.
# The lookahead keeps the separator out of the match, so what follows the
# module name is the argv and nothing has to be re-split off the front.
PY_MODULE = re.compile(r"^(?:python3?(?:\.\d+)?|py)\s+-m\s+(?:openconstructionerp|openestimate)(?=\s|$)")
# `VAR=value ` prefixes, as in `OE_PACK=us-texas openconstructionerp serve`.
ENV_PREFIX = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S*)\s+")
# A systemd unit line: `ExecStart=/home/oe/venv/bin/openconstructionerp serve ...`
UNIT_EXEC = re.compile(r"^Exec(?:Start|Stop|StartPre|StartPost|Reload)=")
# `openconstructionerp v6.4.2` is a version report the CLI prints, not a
# command line. Named here rather than dropped by a heuristic.
VERSION_REPORT = re.compile(r"^v\d")
# `<slug>`, `<archive.zip>`: the reader substitutes their own value. Fed to the
# parser as-is a required positional would look absent, so a stand-in is put in
# its place - `1` after a flag, because it satisfies both `type=int` and a
# plain string, and a readable word elsewhere.
PLACEHOLDER = re.compile(r"^<[^>]+>$")


def repo_root() -> Path:
    """The checkout root, resolved from this file rather than from cwd.

    pytest runs from ``backend/``, and a gate that resolves its own population
    against the working directory finds nothing there and passes.
    """
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def documented_files() -> tuple[str, ...]:
    """Tracked user-facing documents, with the two exclusions applied."""
    root = repo_root()
    listed = subprocess.run(
        ["git", "ls-files", *DOC_PATTERNS],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    keep = []
    for rel in sorted(set(listed)):
        if any(rel.startswith(prefix) for prefix in INTERNAL):
            continue
        if any(rel.startswith(prefix) for prefix in HISTORICAL):
            continue
        keep.append(rel)
    return tuple(keep)


# ── Extraction ────────────────────────────────────────────────────────────
def _strip_markers(line: str) -> str:
    """Remove blockquote, list and shell-prompt decoration from a line."""
    text = line
    while text.lstrip().startswith(">"):
        text = text.lstrip()[1:]
    text = text.strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\$\s+", "", text)
    text = re.sub(r"^PS[^>]*>\s*", "", text)
    return text


def candidates_from_markdown(text: str):
    """Yield ``(line, snippet, channel)`` for every command-looking snippet.

    Two channels, because the defect appeared in both. Fenced blocks carry the
    commands a reader copies; inline code spans carry the ones prose points at,
    including the troubleshooting table that was wrong in exactly the same way
    as the fenced block it referred to.
    """
    in_fence = False
    fence = ""
    continued = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = _strip_markers(line)
        marker = re.match(r"^(```+|~~~+)", stripped)
        if marker:
            if not in_fence:
                in_fence, fence = True, marker.group(1)[:3]
            elif stripped.startswith(fence):
                in_fence, continued = False, False
            continue
        if in_fence:
            # A line whose predecessor ended in a backslash is an argument of
            # that command, not a command of its own. `docker run ... \` puts
            # our own image name on a line by itself.
            was_continued, continued = continued, stripped.endswith("\\")
            if stripped and not was_continued:
                yield number, stripped, "fenced block"
        else:
            for span in re.findall(r"`([^`\n]+)`", line):
                yield number, span.strip(), "inline code"


def candidates_from_html(text: str):
    """Yield the same triples out of ``<code>`` and ``<pre>`` elements."""
    for match in re.finditer(r"<(code|pre)\b[^>]*>(.*?)</\1>", text, re.S):
        inner = re.sub(r"<[^>]+>", "\n", match.group(2))
        number = text.count("\n", 0, match.start()) + 1
        for piece in html.unescape(inner).splitlines():
            piece = piece.strip()
            if piece:
                yield number, piece, "html code element"


def as_invocation(snippet: str) -> tuple[list[str], list[str]] | None:
    """Return ``(argv, env_names)`` for a snippet, or None if it is not our CLI.

    Scoped by command head, so ``pip install openconstructionerp-us-texas`` and
    ``sudo apt install ...`` in the same fence are not ours and are left alone.
    """
    text = re.sub(r"\s+#\s.*$", "", snippet)
    text = UNIT_EXEC.sub("", text)
    text = re.sub(r"^sudo\s+", "", text)

    env_names: list[str] = []
    while (prefix := ENV_PREFIX.match(text)) is not None:
        env_names.append(prefix.group(1))
        text = text[prefix.end() :]

    if (module := PY_MODULE.match(text)) is not None:
        rest = text[module.end() :].strip()
    else:
        head = text.split(None, 1)[0] if text.split() else ""
        # A path is a head too: `/home/oe/venv/bin/openconstructionerp serve`.
        name = head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if name.endswith(".exe"):
            name = name[: -len(".exe")]
        if name not in PROGRAM_NAMES:
            return None
        rest = text[len(head) :].strip()

    if rest and VERSION_REPORT.match(rest.split()[0]):
        return None
    return (shlex.split(rest, posix=False) if rest else []), env_names


# ── Verdict ───────────────────────────────────────────────────────────────
def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def resolve(parser: argparse.ArgumentParser, argv: list[str]) -> tuple[argparse.ArgumentParser, list[str]]:
    """Walk the subcommand chain an argv addresses, and return the parser it lands on."""
    current, chain = parser, []
    for token in argv:
        if token.startswith("-"):
            continue
        action = _subparsers(current)
        if action is not None and token in action.choices:
            current = action.choices[token]
            chain.append(token)
            continue
        break
    return current, chain


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    found: set[str] = set()
    for action in parser._actions:
        found.update(action.option_strings)
    return found


def _fill_placeholders(argv: list[str]) -> list[str]:
    filled = []
    for index, token in enumerate(argv):
        if not PLACEHOLDER.match(token):
            filled.append(token)
            continue
        after_flag = index > 0 and argv[index - 1].startswith("-")
        filled.append("1" if after_flag else "PLACEHOLDER")
    return filled


def rejection(argv: list[str], parser: argparse.ArgumentParser) -> str | None:
    """None when the CLI accepts this command line, else why it does not."""
    if any("[" in token for token in argv):
        return _synopsis_rejection(argv, parser)

    filled = _fill_placeholders(argv)
    try:
        parser.parse_args(filled)
    except SystemExit as exc:
        return f"the parser rejects it (exit {exc.code})"
    except Exception as exc:  # noqa: BLE001 - any parser failure is a rejection
        return f"the parser raised {type(exc).__name__}: {exc}"

    # parse_args alone is not enough: allow_abbrev means a flag that no longer
    # exists can be accepted as a prefix of one that does.
    target, chain = resolve(parser, filled)
    allowed = option_strings(target)
    where = " ".join(["openconstructionerp", *chain])
    for token in filled:
        if not token.startswith("--"):
            continue
        name = token.split("=", 1)[0]
        if name not in allowed:
            return f"`{where}` has no {name} (argparse took it only as an abbreviation)"
    return None


def _synopsis_rejection(argv: list[str], parser: argparse.ArgumentParser) -> str | None:
    """Check a usage synopsis such as ``serve [--host HOST] [--port PORT]``."""
    path = [token for token in argv if "[" not in token and "]" not in token and not token.startswith("<")]
    target, chain = resolve(parser, path)
    allowed = option_strings(target)
    where = " ".join(["openconstructionerp", *chain])
    for group in re.findall(r"\[([^\]]+)\]", " ".join(argv)):
        flag = group.split()[0]
        if not flag.startswith("-"):
            continue
        if flag not in allowed:
            return f"`{where}` has no {flag}"
    return None


def collect() -> tuple[list[tuple[str, int, str, str]], list[tuple[str, int, str, list[str]]], list[str]]:
    """Return (invocations, env-prefixed invocations, files scanned)."""
    root = repo_root()
    files = list(documented_files())
    invocations: list[tuple[str, int, str, str]] = []
    with_env: list[tuple[str, int, str, list[str]]] = []
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if not any(name in text for name in PROGRAM_NAMES):
            continue
        stream = candidates_from_html(text) if rel.endswith(".html") else candidates_from_markdown(text)
        for number, snippet, channel in stream:
            parsed = as_invocation(snippet)
            if parsed is None:
                continue
            argv, env_names = parsed
            invocations.append((rel, number, snippet, channel))
            if env_names:
                with_env.append((rel, number, snippet, env_names))
    return invocations, with_env, files


def _population_report(files: list[str], invocations: list) -> str:
    channels: dict[str, int] = {}
    for _, _, _, channel in invocations:
        channels[channel] = channels.get(channel, 0) + 1
    by_file: dict[str, int] = {}
    for rel, _, _, _ in invocations:
        by_file[rel] = by_file.get(rel, 0) + 1
    lines = [
        "",
        "Population checked against the real argparse parser:",
        f"  documents scanned      {len(files)}",
        f"  documents with commands{len(by_file):>3}",
        f"  invocations checked    {len(invocations)}",
        "  channels               " + ", ".join(f"{name} {count}" for name, count in sorted(channels.items())),
        "  excluded (internal)    " + ", ".join(INTERNAL),
        "  excluded (historical)  " + ", ".join(HISTORICAL) + "  [a release note records the commands of its release]",
        "  files carrying commands:",
    ]
    lines += [f"    {count:>3}  {rel}" for rel, count in sorted(by_file.items())]
    return "\n".join(lines)


# ── The gate ──────────────────────────────────────────────────────────────
def test_every_command_line_in_the_docs_is_accepted_by_the_cli() -> None:
    """No document may print a command line the parser rejects."""
    parser = _build_parser()
    invocations, _, files = collect()

    failures = []
    for rel, number, snippet, channel in invocations:
        argv, _ = as_invocation(snippet)  # type: ignore[misc]
        why = rejection(argv, parser)
        if why is not None:
            failures.append(f"  {rel}:{number} ({channel})\n      {snippet}\n      -> {why}")

    report = _population_report(files, invocations)
    assert not failures, "Documented command lines the CLI rejects:\n\n" + "\n".join(failures) + "\n" + report
    print(report)


def test_the_population_covers_the_pages_a_stuck_reader_reaches() -> None:
    """A narrowed population must fail rather than pass with nothing to check."""
    invocations, _, files = collect()
    carrying = {rel for rel, _, _, _ in invocations}

    missing = [rel for rel in MUST_BE_COVERED if rel not in carrying]
    assert not missing, (
        "These documents print commands and the gate is no longer reading them, "
        f"so its green means nothing for them: {missing}\n" + _population_report(files, invocations)
    )
    assert len(files) >= MINIMUM_FILES, (
        f"only {len(files)} documents in the population, expected at least {MINIMUM_FILES}; "
        "the glob or the exclusions have narrowed"
    )
    assert len(invocations) >= MINIMUM_INVOCATIONS, (
        f"only {len(invocations)} invocations extracted, expected at least {MINIMUM_INVOCATIONS}; "
        "the extractor has stopped seeing commands it used to see"
    )
    print(_population_report(files, invocations))


@lru_cache(maxsize=1)
def _env_names_the_app_reads() -> frozenset[str]:
    """Every environment variable name read anywhere under ``backend/app``."""
    pattern = re.compile(
        r"""(?:environ\.get|getenv|environ\.setdefault)\(\s*["']([A-Z_][A-Z0-9_]*)["']"""
        r"""|environ\[\s*["']([A-Z_][A-Z0-9_]*)["']"""
    )
    found: set[str] = set()
    for path in (repo_root() / "backend" / "app").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "environ" not in text and "getenv" not in text:
            continue
        for match in pattern.finditer(text):
            found.add(match.group(1) or match.group(2))
    return frozenset(found)


def test_an_environment_variable_set_in_front_of_the_cli_is_one_the_app_reads() -> None:
    """``VAR=value openconstructionerp ...`` must name a variable something reads.

    The parser cannot catch this half. ``OE_PORT=9090 openconstructionerp``
    parses perfectly, starts on 8080 and says nothing, which is worse than the
    flag that at least exits 2 and tells the reader something is wrong.
    """
    _, with_env, _ = collect()
    known = _env_names_the_app_reads()

    failures = []
    for rel, number, snippet, names in with_env:
        for name in names:
            if name not in known:
                failures.append(
                    f"  {rel}:{number}\n      {snippet}\n"
                    f"      -> nothing under backend/app reads {name}, so this line "
                    "changes nothing and reports nothing"
                )

    checked = sorted({name for _, _, _, names in with_env for name in names})
    assert not failures, (
        "Documented environment variables the application does not read:\n\n"
        + "\n".join(failures)
        + f"\n\nChecked {len(with_env)} env-prefixed invocations naming {checked} "
        f"against {len(known)} names read under backend/app."
    )
    print(f"Checked {len(with_env)} env-prefixed invocations naming {checked}.")


# ── The same defect one layer in ──────────────────────────────────────────
def _prose_rejection(text: str, parser: argparse.ArgumentParser) -> str | None:
    """Check a command named inside a sentence, values ignored.

    Runtime hints interpolate real paths, and a Windows home directory has a
    space in it, so tokenising the hint would split the path and invent a
    failure. Only the subcommand and the flags are checked, which is what the
    reader has to get right.
    """
    match = re.search(r"\bopenconstructionerp\b(?![-.:])", text)
    if match is None:
        return "it names no command to type"
    tail = text[match.end() :]
    tokens = tail.replace("'", " ").replace("`", " ").split()
    subcommands = _subparsers(parser).choices  # type: ignore[union-attr]
    chain = []
    target = parser
    for token in tokens:
        if token.startswith("-"):
            break
        if token in subcommands and target is parser:
            chain.append(token)
            target = subcommands[token]
            continue
        break
    allowed = option_strings(target)
    where = " ".join(["openconstructionerp", *chain])
    flags = [token for token in tokens if token.startswith("--")]
    if not flags:
        return None
    for flag in flags:
        if flag.split("=", 1)[0] not in allowed:
            return f"`{where}` has no {flag}"
    return None


def test_the_hint_for_a_busy_port_names_a_command_that_accepts_the_flag() -> None:
    """The check that fires on the commonest first-run failure must be typable.

    A reader who typed the one command the docs teach, ``openconstructionerp``,
    and hit a busy port is shown this hint. It used to say "use --port 8081"
    and name no command, so following it literally produced the same exit 2
    the documentation defect produced.
    """
    import socket

    parser = _build_parser()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        check = check_port_free("127.0.0.1", port)

    if check.status != "error":
        pytest.skip(f"could not reproduce a busy port on this host: {check.status} {check.message}")
    why = _prose_rejection(check.hint, parser)
    assert why is None, f"the busy-port hint is not typable:\n  {check.hint}\n  -> {why}"
    print(f"busy-port hint checked: {check.hint}")


def test_the_hint_for_an_unwritable_data_directory_names_a_command(tmp_path: Path) -> None:
    """Same defect, same check function, the other blocking preflight."""
    parser = _build_parser()
    blocker = tmp_path / "a-file-not-a-directory"
    blocker.write_text("", encoding="utf-8")

    check = check_data_dir(blocker / "workspace")
    assert check.status == "error", f"expected an unwritable data directory, got {check.status}"
    why = _prose_rejection(check.hint, parser)
    assert why is None, f"the unwritable-data-directory hint is not typable:\n  {check.hint}\n  -> {why}"
    print(f"data-directory hint checked: {check.hint}")
