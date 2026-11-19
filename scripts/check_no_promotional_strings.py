#!/usr/bin/env python3
"""No promotional or upstream-attribution strings in anything the product renders.

The owner ships this product as their own. Nothing a user can see should tell
them it is open source, that it is built on somebody else's project, or that
there is a community to join somewhere else. This guard is what keeps that true
after the cleanup: it fails when a *rendered* string carries one of the claims
below, so the next marketing line cannot be added by accident.

What is scanned, and why only that:

  * locale values - the `"key": "value"` pairs in frontend/src/app/locales/*.ts.
    These are what users actually read, in every language.
  * component strings - string literals and JSX text in .tsx/.ts under
    frontend/src. Comments are deliberately NOT scanned: they are not rendered,
    and the comments that explain why a promotional surface was removed have to
    be able to name it. Same for test files, which assert absence and so must be
    allowed to quote the thing that is absent.
  * assembled strings - the copy that only exists once a file is read as a whole
    rather than a line at a time: JSX text spanning lines, two literals joined by
    `+`, and template literals read as the static text they produce with their
    `${...}` holes dropped. This is the shape the register page hid behind: a
    badge whose words were bare JSX text between `</svg>` and `<Link>`, on two
    lines, so no quoted literal ever existed for the line-based read to find.
    Every pattern is a bounded regex; none is a state machine, because one of
    those once swallowed a 6,000-line file and mis-reported every later line.
  * icon signatures - marks that carry a claim without carrying a word, matched
    on their svg path data. The same badge was an octocat beside the text, so a
    guard that only reads words waves the mark through the day somebody deletes
    the words and keeps the picture.

What is exempt, and why:

  * the legal floor - LICENSE, NOTICE, COPYRIGHT and the /legal page. Stating the
    licence is an obligation under AGPL-3.0 section 5 and 13, not promotion.
  * the copyright header on the first lines of every source file (same reason).
  * generated files, which would otherwise fail on content nobody wrote.
  * scripts/promotional_allowlist.json - entries with a written reason. These are
    functional, not promotional: the converter and CWICR components are downloaded
    from where their publisher puts them, so the product has to name that source,
    and the Telegram/Slack/Teams entries under integrations.* are notification
    channels the user configures, not a community to join.
  * scripts/promotional_debt_baseline.json - a per-file count of violations that
    were already in the tree when this guard landed. This is labelled debt, NOT
    permission: the guard fails if any file's count grows or a new file appears,
    so the number can only go down. Work through it and lower the baseline in the
    same diff.

Exit 0 means clean. Exit 1 prints every new violation with its file and line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every relative path below is taken with as_posix(), never str(). str() of a
# Path uses the platform separator, so on a Windows checkout the exemption
# patterns - "frontend/src/features/legal/", "/locales/", "__tests__", "/tests/"
# - matched nothing at all, and the guard reported the licence page and all 45
# locale bundles as new violations. It failed on Windows while passing on Linux,
# which is what it did in CI inside a backend unit test that ran it as a
# subprocess. The baseline files are keyed with forward slashes as well, so
# normalising keeps their counts comparable across platforms too.
LOCALES = ROOT / "frontend" / "src" / "app" / "locales"
SRC = ROOT / "frontend" / "src"
ALLOWLIST = ROOT / "scripts" / "promotional_allowlist.json"
BASELINE = ROOT / "scripts" / "promotional_debt_baseline.json"

# Claims that must not reach a user. Case-insensitive except where the spelling
# itself is the tell (#1, and the project names).
FORBIDDEN = [
    "open source",
    "open-source",
    "opensource",
    "AGPL",
    "GitHub",
    "Telegram",
    "openconstructionerp",
    "DataDrivenConstruction",
    "Data Driven Construction",
    "#1",
]
# "#1" only as the marketing claim. Unqualified it matched CSS hex colours
# ('#10b981') and licence placeholders ("CA License #1234567"), which is how 106
# component hits and 38 locale hits entered the baseline that were never a claim
# about being number one. A hex colour always continues with a hex digit; the
# claim never does.
HEX_TAIL = re.compile(r"#1[0-9a-fA-F]")
# "#1" only when it claims to be first. Two more classes turned up once the
# backend was scanned: IFC/STEP entity identifiers are written "#1=IFCPROJECT",
# where the number is a handle and not a rank, and ordinary ordinals - "Weekly
# progress meeting #1", "Pay application #1" - number a document in a sequence.
# Neither says anything about the product. The claim always reads "the #1 <noun>"
# or stands alone as a headline, so it is matched in that shape only. The
# headline form needs the lookahead rather than a word boundary: in "#1=IFCPROJECT"
# the "=" is itself a boundary, so \b let every IFC entity identifier through as a
# rank claim. What follows a headline "#1" is a space or nothing, never "=".
RANK_CLAIM = re.compile(r"\b(?:the|world'?s|region'?s|industry'?s)\s+#1\b|^#1(?![=\w-])", re.I)
# AGPL as a word, not a substring. Matched loosely it fired inside ordinary words
# in two languages: Danish "Tagplantrum" (a roof plant room) and Filipino
# "Magplano" (to plan) both contain "agpl". Twenty keys across da.ts and fil.ts
# were baselined as licence claims for that reason alone. The acronym is always
# written in capitals in real use, and a word boundary keeps "AGPL-3.0" matching
# while leaving both languages alone.
AGPL_WORD = re.compile(r"\bAGPL\b")
# "free" only in its marketing sense. On its own the word is everywhere in this
# product for legitimate reasons (free text, free-form, duty-free, risk-free),
# so it is matched in the collocations that make it a sales claim.
FREE_MARKETING = re.compile(
    r"\b(?:100%|completely|totally|entirely|absolutely|forever|always)\s+free\b"
    r"|\bfree\s+(?:and\s+)?open[\s-]?source\b"
    r"|\bfree\s+forever\b"
    r"|\b(?:it'?s|it\s+is)\s+free\b",
    re.I,
)
# "free text" / "free-text" is a field type in this domain, not a price claim, and
# "whether it is free text" matched the collocation above in four backend files.
# A price claim never has the word "text" or "form" immediately after it.
FREE_NOT_MARKETING = re.compile(r"\bfree[\s-]+(?:text|texts|form|format|response|entry|issue|hand)\b", re.I)

# Files that are the legal floor, or that this guard must not read as product UI.
EXEMPT_PATHS = (
    "frontend/src/features/legal/",  # the one plain Legal page
    "frontend/public/legal/",
)
EXEMPT_NAMES = {"LICENSE", "NOTICE", "COPYRIGHT", "LICENSE.txt", "NOTICE.txt"}
GENERATED = {"architecture_manifest.json"}
HEADER_LINES = 8  # the copyright/SPDX header every source file carries


def hits(text: str) -> list[str]:
    found = [w for w in FORBIDDEN if w.lower() in text.lower()]
    if "#1" in found and not RANK_CLAIM.search(HEX_TAIL.sub("", text)):
        found.remove("#1")
    if "AGPL" in found and not AGPL_WORD.search(text):
        found.remove("AGPL")
    if FREE_MARKETING.search(text) and not FREE_NOT_MARKETING.search(text):
        found.append("free (marketing)")
    return found


def locale_value(line: str) -> str | None:
    m = re.match(r'\s*"([^"]+)":\s*"(.*)",?\s*$', line)
    return m.group(2) if m else None


STRING_RE = re.compile(r"'([^'\n]{2,400})'" + r'|"([^"\n]{2,400})"' + r"|`([^`\n]{2,400})`")
JSX_TEXT_RE = re.compile(r">\s*([^<>{}\n]{2,200}?)\s*<")


def component_strings(text: str) -> list[tuple[int, str]]:
    """Quoted literals and JSX text nodes, with comments excluded.

    Line-based on purpose. An earlier version walked the file character by
    character to track string and comment state, and one unterminated state in a
    6,000-line TSX file swallowed the rest of the file: every later hit was
    reported at the same line number, quoting comment text as if it were a
    string. A guard that reports the wrong line is worse than no guard, because
    it sends whoever reads it to the wrong place.

    What this covers: single, double and back-quoted literals on one line (so
    `defaultValue: 'GitHub repository'` is caught) and text between two tags on
    one line (so `<span>GitHub</span>` is caught). What it does not cover is a
    literal or a text node split across lines. That is a real limitation and it
    is accepted because nearly every string this product renders goes through
    t() and so is scanned as a locale value above, where the coverage is exact.
    """
    out: list[tuple[int, str]] = []
    in_block = False
    for ln, line in enumerate(text.splitlines(), 1):
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        stripped = line.strip()
        if stripped.startswith(("/*", "{/*", "/**")):
            if "*/" not in line:
                in_block = True
            continue
        if stripped.startswith(("//", "*", "*/")):
            continue
        for m in STRING_RE.finditer(line):
            val = next((g for g in m.groups() if g is not None), "")
            if val:
                out.append((ln, val))
        for m in JSX_TEXT_RE.finditer(line):
            if m.group(1).strip():
                out.append((ln, m.group(1).strip()))
    return out


BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
# JSX text that starts on one line and ends on another: `>` at the end of a line,
# the words on the next, `</span>` after them. Bounded on purpose - no braces, no
# angle brackets, no `=` and no `;` inside, so a run of code between an arrow
# function and a comparison (`items.map((i) => i < 10)`) cannot read as copy - and
# capped at four lines, because a JSX text node that long is a paragraph nobody
# ships in one piece and a match that long is more likely to be code.
JSX_TEXT_SPANNING = re.compile(r">([^<>{}=;\n]{0,200}\n[^<>{}=;]{2,400}?)<", re.S)
# Two literals joined by `+` on one line: 'open' + ' source'. Each half is innocent
# on its own, which is why the literal-by-literal read above cannot see it.
LITERALS_JOINED = re.compile(
    r"(?P<q1>['\"])(?P<v1>[^'\"\n]{1,200})(?P=q1)\s*\+\s*"
    r"(?P<q2>['\"])(?P<v2>[^'\"\n]{1,200})(?P=q2)"
)
# A template literal opened on one line and closed on a later one. Read as the text
# it will actually produce: the ${...} holes dropped, the static words kept.
TEMPLATE_SPANNING = re.compile(r"`([^`]{2,600}?)`", re.S)
TEMPLATE_HOLE = re.compile(r"\$\{[^{}]*\}")
# Marks that carry a claim without carrying a word. A GitHub badge is an octocat in
# a <svg> path next to text that may be perfectly innocent, so a guard that only
# reads words waves it through - which is what happened on the register page, where
# the mark and "Open Source · AGPL-3.0" were one badge. Matched on the start of the
# path data, which is the same in every copy of the mark.
ICON_SIGNATURES = {
    "GitHub mark (octocat svg path)": "M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387",
}


def strip_comments(text: str) -> str:
    """Blank the comments, keeping every newline and every character count.

    Blank rather than removed, so the line numbers the spanning patterns report are
    the line numbers a reader will find. ``://`` is left alone: a URL inside a string
    literal is not a comment, and blanking from it would eat the rest of the line.
    A ``//`` inside a string literal *is* treated as a comment, and that is accepted:
    the literal-by-literal read below still sees the whole string, so a claim hidden
    there is reported by the pass that reads literals rather than missed.
    """
    return LINE_COMMENT.sub(_blank, BLOCK_COMMENT.sub(_blank, text))


def assembled_strings(text: str) -> list[tuple[int, str]]:
    """Copy that only exists once the source is read as a whole, not line by line.

    The line-based read above is deliberate and its docstring defends it: a character
    state machine once swallowed a 6,000-line file and reported every later hit at
    the same line. What it cannot see is the three shapes below, and one of them -
    JSX text split across lines - is how a "Open Source · AGPL-3.0" badge sat on the
    register page, in a tree this guard reported clean, until an owner's screenshot
    found it. So these are regexes over the whole text, each bounded by a character
    class or a line cap, none of them a state machine.

    Covered: a JSX text node whose opening tag, words and closing tag are on
    different lines; two literals joined by ``+``, on one line or across two; and a
    template literal spanning lines, read as the static text it produces with its
    ``${...}`` holes dropped. Not covered, and stated rather than left to be trusted:
    a phrase assembled from three or more pieces, one built by a helper function, or
    one arriving from a variable - a guard that reads text cannot follow data.
    """
    out: list[tuple[int, str]] = []
    work = strip_comments(text)
    lines = work.splitlines()

    for m in JSX_TEXT_SPANNING.finditer(work):
        value = m.group(1).strip()
        # Letters required: a run of punctuation and whitespace between two tags is
        # layout, not copy, and it is where false positives come from.
        if value and any(ch.isalpha() for ch in value) and value.count("\n") <= 3:
            out.append((_line_of(work, m.start()), value.replace("\n", " ")))

    for m in LITERALS_JOINED.finditer(work):
        joined = f"{m.group('v1')}{m.group('v2')}"
        if joined.strip():
            out.append((_line_of(work, m.start()), joined))

    for m in TEMPLATE_SPANNING.finditer(work):
        body = m.group(1)
        if "\n" not in body:
            continue  # a one-line template is already read by STRING_RE
        static = TEMPLATE_HOLE.sub(" ", body).strip()
        if static and any(ch.isalpha() for ch in static):
            out.append((_line_of(work, m.start()), " ".join(static.split())))

    # A chain broken over a line end: a literal, then `+` alone at the end of the
    # line, then the next literal on the line below.
    for i, line in enumerate(lines[:-1]):
        if not line.rstrip().endswith("+"):
            continue
        head = list(STRING_RE.finditer(line))
        tail = STRING_RE.search(lines[i + 1])
        if head and tail:
            first = next((g for g in head[-1].groups() if g is not None), "")
            second = next((g for g in tail.groups() if g is not None), "")
            if first and second:
                out.append((i + 1, f"{first}{second}"))
    return out


def icon_signatures(text: str) -> list[str]:
    """Which recognisable marks a file carries, by path data rather than by word."""
    return [name for name, path in ICON_SIGNATURES.items() if path in text]


BACKEND = ROOT / "backend" / "app"
BACKEND_BASELINE = ROOT / "scripts" / "promotional_debt_baseline_backend.json"

# Only the backend surfaces whose strings reach a user, and only because most of
# backend/app is internal: a variable name, a log line, a SQL fragment or a
# docstring is not something an operator reads. Each entry below produces text
# that leaves the process - rendered into an e-mail, stamped into a PDF or an
# exported file, served as API documentation, or printed by the CLI.
#
# What this list deliberately does NOT cover: router and service modules whose
# strings go to logs, exception messages and internal identifiers. A promotional
# string added there would not be caught. That is a real limit and it is stated
# here rather than left for someone to discover by trusting a green run.
BACKEND_USER_VISIBLE = (
    "backend/app/cli.py",
    "backend/app/cli_static.py",
    "backend/app/main.py",
    "backend/app/core/email/",
    "backend/app/core/pdf_branding.py",
    "backend/app/core/pdf_appearance.py",
    "backend/app/core/pdf_stamp.py",
    "backend/app/core/register_export.py",
    "backend/app/core/demo_placeholders.py",
    "backend/app/core/partner_pack/",
    "backend/app/modules/validation/sarif_exporter.py",
    "backend/app/modules/bcf/",
    "backend/app/modules/bim_hub/exporters/",
    "backend/app/modules/bim_requirements/exporters",
    "backend/app/modules/design_options/exporters",
    "backend/app/modules/boq/pdf_export.py",
    "backend/app/modules/tendering/pdf_documents.py",
    "backend/app/modules/module_builder/",
    # Module manifests are data the Modules page renders: author, display_name and
    # description reach the screen through the modules API. 202 of them carried the
    # old product name in the author field before they were cleaned, and nothing
    # caught it, because a manifest is not an exporter, an e-mail, a PDF, the CLI
    # or the OpenAPI document - it is a Python file whose strings happen to be
    # shown. Listed as a glob so a new module is covered the day it is created.
    "backend/app/modules/*/manifest.py",
    # Seeded demo content is rendered as if the user created it: project and
    # meeting names, document placeholders, marketplace cards and the demo
    # accounts an operator signs in with.
    "backend/app/core/demo_projects.py",
    "backend/app/core/demo_accounts.py",
    "backend/app/core/marketplace.py",
)


def python_strings(text: str) -> list[tuple[int, str]]:
    """String literals in Python source, with comments and docstrings excluded.

    Docstrings are excluded for the same reason the frontend scan excludes
    comments: they are not rendered, and the ones explaining why a promotional
    surface was removed have to be able to name it. A docstring is recognised by
    position - it is the first statement after a ``def``, ``class``, decorator or
    ``:`` line, or of a file - and both shapes are handled, the multi-line block
    and the single line that opens and closes at once. An earlier draft skipped
    only the opening line, so every docstring body was scanned as prose and
    inflated the count with text no user ever sees.
    """
    out: list[tuple[int, str]] = []
    in_doc: str | None = None
    in_str: str | None = None
    prev = ""
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if in_doc:
            if in_doc in stripped:
                in_doc = None
            continue
        if in_str:
            if in_str in line:
                out.append((ln, line.split(in_str)[0]))
                in_str = None
            else:
                out.append((ln, line))
            continue
        if stripped.startswith("#"):
            continue
        doc_pos = prev == "" or prev.endswith(":") or prev.startswith(("def ", "class ", "async def ", "@"))
        opened = next((d for d in ('"""', "'''") if line.count(d) % 2 == 1), None)
        if opened:
            if doc_pos:
                in_doc = opened
            else:
                in_str = opened
                out.append((ln, line.split(opened, 1)[1]))
            prev = stripped
            continue
        if doc_pos and stripped.startswith(('"""', "'''")):
            prev = stripped
            continue  # a docstring that opens and closes on one line
        code = line
        hash_at = code.find(" #")
        if hash_at > 0 and code[:hash_at].count('"') % 2 == 0 and code[:hash_at].count("'") % 2 == 0:
            code = code[:hash_at]
        for m in STRING_RE.finditer(code):
            val = next((g for g in m.groups() if g is not None), "")
            if val:
                out.append((ln, val))
        prev = stripped
    return out


def backend_files() -> list[Path]:
    """Every file the backend scan reads, from the declared surface list.

    A directory means all of its Python files; anything else is a glob relative to
    the repository root, so "backend/app/modules/*/manifest.py" picks up the
    manifest of every module including one added tomorrow. Globbing rather than
    naming files is the point: a list of today's filenames silently stops covering
    the tree as it grows, which is how 202 module manifests went unscanned.
    """
    out: list[Path] = []
    for pat in BACKEND_USER_VISIBLE:
        p = ROOT / pat
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*.py") if x.is_file()))
        else:
            out.extend(sorted(x for x in ROOT.glob(pat) if x.is_file() and x.suffix == ".py"))
    seen: set[Path] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


# The browser-level surfaces: what a tab, an install prompt or an installer says
# about this product before any of the code above has run.
#
# The two scans above read locale bundles, the .ts/.tsx under frontend/src, and the
# backend files whose strings leave the process. Neither reads the documents a
# browser or a package manager presents first, and those are the ones a visitor
# reads earliest: the tab title, the description a search result or a chat preview
# shows, the name and description in the PWA install prompt, and the text an
# installer writes into Add/Remove Programs, Info.plist and the .desktop entry.
#
# An owner's screenshot of the rebranded sign-in page showed the tab still reading
# "Construction AI OS - Open-Source Construction Cost Estimation Platform" after
# every string the product renders had been cleaned. frontend/index.html is not
# under frontend/src, so no scan reached it, and the same was true of the PWA
# manifest literal in frontend/vite.config.ts and of the two bundle descriptions in
# desktop/src-tauri/tauri.conf.json. These paths close that.
#
# What is deliberately NOT here: frontend/public/legal/ and the .txt licence texts
# under frontend/public/assets/vendor/fonts/licenses/, which are the legal floor and
# third-party licence notices their own licences require be kept verbatim, and
# frontend/public/README.md, which is a developer note the server never hands out.
BROWSER_SURFACES = (
    "frontend/index.html",
    "frontend/vite.config.ts",  # the PWA manifest is a literal here, not a file
    "frontend/package.json",
    "frontend/public/**/*.html",
    "frontend/public/**/*.js",
    "frontend/public/**/*.json",
    "frontend/public/**/*.webmanifest",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/src-tauri/Cargo.toml",
)

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HTML_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.S | re.I)
HTML_META_TAG = re.compile(r"<meta\b[^>]*>", re.S | re.I)
HTML_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
HTML_TEXT_RUN = re.compile(r">([^<>]{2,600})<", re.S)
HTML_ATTR_VALUE = re.compile(r"\b(href|alt|aria-label|placeholder)\s*=\s*[\"']([^\"']{2,600})[\"']", re.I)
JSON_PAIR = re.compile(r'"([A-Za-z_@][\w.@:-]*)"\s*:\s*"((?:[^"\\]|\\.){1,600})"')
TOML_PAIR = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*=\s*(.+?)\s*$")


def _line_of(text: str, pos: int) -> int:
    """The 1-based line a match offset falls on."""
    return text.count("\n", 0, pos) + 1


def _blank(match: re.Match[str]) -> str:
    """Whitespace the same shape as the match, newlines kept where they were.

    Blank rather than deleted: every extractor here reports a line number, and
    closing the gap would move the lines underneath the text still to be read, so
    the guard would send whoever reads it to the wrong place.
    """
    return re.sub(r"[^\n]", " ", match.group(0))


def html_strings(text: str) -> list[tuple[int, str, str]]:
    """The values an HTML document puts in front of a reader or a crawler.

    Comments are read, then dropped. They used to be dropped unread, on the reasoning
    that a comment is not rendered - which was true of the reader and false of the
    guard, and left the whole class unpoliced: the note in frontend/index.html naming
    a deployment script that injects analytics into the shipped page was never judged
    by anything, and neither would the next one be. A comment is copy somebody wrote
    into a page this product serves, so it is scanned under the key ``comment``, and
    the attribution notice that used to live in one now lives in the two ``meta``
    elements ``scripts/check_built_html_comments.py`` requires, allowlisted by their
    own keys rather than by a substring wide enough to hide a claim beside them.

    Keys are the document's own - ``title``, ``meta:og:title``, ``uPrivacy`` - not
    line numbers, for the reason the locale scan prefers an i18n key: an entry keyed
    to a line drifts the first time anything above it is edited. The splash screen
    makes that concrete, carrying one privacy sentence in 29 languages, which a
    single keyed entry covers and 29 line entries would not.
    """
    out: list[tuple[int, str, str]] = []

    # Read before blanking, so the text a page carries is judged whatever element of
    # it carries it. The delimiters are cut rather than matched around: a comment is
    # its body, and a body that is only whitespace has nothing to say.
    for m in HTML_COMMENT.finditer(text):
        body = " ".join(m.group(0)[4:-3].split())
        if body:
            out.append((_line_of(text, m.start()), "comment", body))

    work = HTML_COMMENT.sub(_blank, text)

    for m in HTML_TITLE.finditer(work):
        if m.group(1).strip():
            out.append((_line_of(work, m.start()), "title", m.group(1).strip()))
    work = HTML_TITLE.sub(_blank, work)

    # Meta tags are read as tags, not as attribute soup, so the key names the tag a
    # value came from: og:title and twitter:title are different claims even when the
    # words in them are the same.
    for m in HTML_META_TAG.finditer(work):
        tag = m.group(0)
        name = re.search(r"\b(?:name|property)\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        content = re.search(r"\bcontent\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
        if name and content and content.group(1).strip():
            out.append((_line_of(work, m.start()), f"meta:{name.group(1)}", content.group(1).strip()))
    work = HTML_META_TAG.sub(_blank, work)

    # Quoted "key": "value" pairs, which is the JSON-LD block in index.html and the
    # 29-language table the desktop splash screen is built from. Read before the
    # script bodies are blanked, because that is where both of them live.
    for m in JSON_PAIR.finditer(work):
        out.append((_line_of(work, m.start()), m.group(1), m.group(2)))
    work = JSON_PAIR.sub(_blank, work)

    # What is left of a script or a style body is code, not copy: the appearance boot
    # script in index.html is JavaScript, and reporting a variable name as a sentence
    # a user reads would be the guard crying wolf.
    work = HTML_SCRIPT.sub(_blank, work)

    # Text between tags, including a run that spans lines - which is how the licence
    # paragraphs in terms.html are written, and what a line-based read misses.
    for m in HTML_TEXT_RUN.finditer(work):
        if m.group(1).strip():
            out.append((_line_of(work, m.start()), "text", m.group(1).strip()))
    for m in HTML_ATTR_VALUE.finditer(work):
        if m.group(2).strip():
            out.append((_line_of(work, m.start()), f"attr:{m.group(1).lower()}", m.group(2).strip()))
    return out


def json_strings(text: str) -> list[tuple[int, str, str]]:
    """``"key": "value"`` pairs of a JSON manifest, keyed by the property name.

    Read as pairs rather than parsed, so a manifest that does not parse still gets
    scanned: a broken file is a reason to look at it, not a reason to skip it.
    """
    return [(_line_of(text, m.start()), m.group(1), m.group(2)) for m in JSON_PAIR.finditer(text)]


def toml_strings(text: str) -> list[tuple[int, str, str]]:
    """``key = value`` lines of a Cargo manifest, skipping comments and headers."""
    out: list[tuple[int, str, str]] = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "[")):
            continue
        m = TOML_PAIR.match(line)
        if not m:
            continue
        value = m.group(2).strip().strip("\"'")
        if value:
            out.append((ln, m.group(1), value))
    return out


def browser_files() -> list[Path]:
    """Every existing file the browser-surface patterns resolve to, exemptions applied."""
    out: list[Path] = []
    for pat in BROWSER_SURFACES:
        for p in ROOT.glob(pat):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT).as_posix()
            if any(rel.startswith(x) for x in EXEMPT_PATHS) or p.name in EXEMPT_NAMES:
                continue
            out.append(p)
    return sorted(set(out))


def browser_triples(path: Path, text: str) -> list[tuple[int, str, str]]:
    """The (line, key, value) triples to judge, by the kind of file this is."""
    if path.suffix == ".html":
        return html_strings(text)
    if path.suffix in {".json", ".webmanifest"}:
        return json_strings(text)
    if path.suffix == ".toml":
        return toml_strings(text)
    # A .ts or .js surface: the same literal-and-text read the component scan uses,
    # which excludes comments and reports the line a literal sits on.
    return [(ln, f"line {ln}", value) for ln, value in component_strings(text)]


def main() -> int:
    allow: dict[str, str] = {}
    if ALLOWLIST.exists():
        allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    # An entry written "=literal" matches only a string that is exactly that
    # literal; every other entry matches as a substring. The distinction exists
    # because some functional strings are single words that also appear inside
    # promotional sentences. Allowing the substring "Telegram" would exempt the
    # bare channel identifier defaultName: 'Telegram' and, with it, any future
    # "join our Telegram community". Allowing "=Telegram" exempts the identifier
    # and nothing else. The same reasoning kept "on GitHub" out of the allowlist:
    # it would have re-permitted the tour step this cleanup deleted.
    allow_exact = {k[1:] for k in allow if k.startswith("=")}
    allow_sub = [k for k in allow if not k.startswith("=")]

    def allowed(text: str, key: str) -> bool:
        return key in allow or text in allow_exact or any(pat in text for pat in allow_sub)

    baseline: dict[str, int] = {}
    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8")).get("counts", {})

    violations: dict[str, list[str]] = {}

    def record(rel: str, key: str, text: str, found: list[str]) -> None:
        if rel in EXEMPT_PATHS or any(rel.startswith(p) for p in EXEMPT_PATHS):
            return
        # An allowlist entry is either the exact i18n key, or a substring that
        # identifies a literal (component lines have no stable key, so a pattern
        # is the only handle that survives an unrelated edit above them).
        if allowed(text, key):
            return
        violations.setdefault(rel, []).append(f"{key}: {', '.join(found)} -> {text[:90]!r}")

    for p in sorted(LOCALES.glob("*.ts")):
        rel = p.relative_to(ROOT).as_posix()
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ln <= HEADER_LINES:
                continue
            val = locale_value(line)
            if val is None:
                continue
            key = line.split('"', 2)[1]
            found = hits(val)
            if found:
                record(rel, key, val, found)

    for p in sorted(SRC.rglob("*")):
        if not p.is_file() or p.suffix not in {".ts", ".tsx"}:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if p.name in GENERATED or ".test." in p.name or "__tests__" in rel or "/locales/" in rel:
            continue
        if any(rel.startswith(x) for x in EXEMPT_PATHS) or p.name in EXEMPT_NAMES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        # Before the word prefilter below, because a mark carries its claim without
        # carrying a word: a file holding only the octocat path would otherwise be
        # skipped without being read.
        for name in icon_signatures(text):
            record(rel, "icon signature", name, ["GitHub mark"])
        if not any(w.lower() in text.lower() for w in FORBIDDEN) and not FREE_MARKETING.search(text):
            continue
        lines = text.splitlines()
        for ln, lit in assembled_strings(text):
            found = hits(lit)
            if not found or ln <= HEADER_LINES:
                continue
            src = lines[ln - 1] if ln - 1 < len(lines) else ""
            if any(f"'{k}'" in src or f'"{k}"' in src for k in allow):
                continue
            record(rel, f"line {ln} (assembled)", lit, found)
        for ln, lit in component_strings(text):
            found = hits(lit)
            if not found or ln <= HEADER_LINES:
                continue
            # A defaultValue on the line that renders an allowlisted key is the
            # same string the key stands for, so it gets the same treatment.
            # boq.source_open is the case that needs it: its default is the two
            # words "Open source", where "Open" is a verb and "source document"
            # is what it opens. Allowlisting the bare phrase would exempt every
            # real occurrence of it, so the exemption is tied to the key.
            src = lines[ln - 1] if ln - 1 < len(lines) else ""
            if any(f"'{k}'" in src or f'"{k}"' in src for k in allow):
                continue
            record(rel, f"line {ln}", lit, found)

    # The browser-level surfaces, judged with the same allowlist and the same empty
    # baseline as everything else. A surface newly brought under the guard is never
    # baselined into existence: every string in it is either clean, fixed, or carried
    # in scripts/promotional_allowlist.json with a written reason that says whether it
    # is the legal floor or a functional statement. Both debt baselines stay at zero,
    # which backend/tests/unit/test_no_promotional_strings_reach_a_user.py reads
    # directly rather than trusting.
    for p in browser_files():
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        for name in icon_signatures(text):
            record(rel, "icon signature", name, ["GitHub mark"])
        for _ln, key, value in browser_triples(p, text):
            found = hits(value)
            if found:
                record(rel, key, value, found)
        if p.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            for ln, value in assembled_strings(text):
                found = hits(value)
                if found and ln > HEADER_LINES:
                    record(rel, f"line {ln} (assembled)", value, found)

    backend_violations: dict[str, list[str]] = {}
    for p in backend_files():
        rel = p.relative_to(ROOT).as_posix()
        if "/tests/" in rel or rel.endswith("_test.py"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not any(w.lower() in text.lower() for w in FORBIDDEN) and not FREE_MARKETING.search(text):
            continue
        for ln, lit in python_strings(text):
            if ln <= HEADER_LINES:
                continue
            found = hits(lit)
            if not found:
                continue
            if allowed(lit, f"line {ln}"):
                continue
            backend_violations.setdefault(rel, []).append(f"line {ln}: {', '.join(found)} -> {lit[:90]!r}")

    new: list[str] = []
    for rel, items in sorted(violations.items()):
        allowed_n = baseline.get(rel, 0)
        if len(items) > allowed_n:
            new.append(f"{rel}: {len(items)} violation(s), baseline allows {allowed_n}")
            new.extend(f"    {i}" for i in items[allowed_n:])
    for rel in sorted(baseline):
        if rel not in violations:
            print(f"note: {rel} is clean now - lower its baseline entry ({baseline[rel]} -> 0)")

    backend_baseline: dict[str, int] = {}
    if BACKEND_BASELINE.exists():
        backend_baseline = json.loads(BACKEND_BASELINE.read_text(encoding="utf-8")).get("counts", {})
    backend_new: list[str] = []
    for rel, items in sorted(backend_violations.items()):
        allowed_n = backend_baseline.get(rel, 0)
        if len(items) > allowed_n:
            backend_new.append(f"{rel}: {len(items)} violation(s), baseline allows {allowed_n}")
            backend_new.extend(f"    {i}" for i in items[allowed_n:])
    for rel in sorted(backend_baseline):
        if rel not in backend_violations:
            print(f"note: {rel} is clean now - lower its backend baseline entry ({backend_baseline[rel]} -> 0)")

    if "--write-baseline" in sys.argv:
        counts = {rel: len(items) for rel, items in sorted(violations.items())}
        BASELINE.write_text(
            json.dumps(
                {
                    "_comment": (
                        "Per-file counts of promotional strings that were already in the tree when "
                        "check_no_promotional_strings.py landed. This is labelled debt, not "
                        "permission: the guard fails if any count grows or a new file appears, so "
                        "these numbers can only go down. Lower an entry in the same diff that "
                        "removes the strings it counts."
                    ),
                    "counts": counts,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"baseline written: {len(counts)} file(s), {sum(counts.values())} violation(s) recorded as debt")
        BACKEND_BASELINE.write_text(
            json.dumps(
                {
                    "_comment": (
                        "Per-file counts of promotional strings in the backend surfaces whose text "
                        "reaches a user: e-mail templates, PDF and export producer strings, OpenAPI "
                        "documentation and CLI output. Labelled debt, not permission - the guard "
                        "fails if a count grows or a new file appears. The target is an empty file."
                    ),
                    "counts": {rel: len(items) for rel, items in sorted(backend_violations.items())},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"backend baseline written: {len(backend_violations)} file(s), "
            f"{sum(len(v) for v in backend_violations.values())} violation(s) recorded as debt"
        )
        return 0

    if backend_new:
        print("ERROR: promotional or upstream-attribution strings reach users from the backend.")
        print("\n".join(backend_new[:120]))
        if len(backend_new) > 120:
            print(f"... and {len(backend_new) - 120} more")
        print(
            "\nFix by removing the string or by naming this product instead. If it is functional "
            "(a download source, a package identifier, a licence statement the law requires), add "
            "it to scripts/promotional_allowlist.json with a written reason."
        )
        return 1

    if new:
        print("ERROR: promotional or upstream-attribution strings reach the product UI.")
        print("\n".join(new[:120]))
        if len(new) > 120:
            print(f"... and {len(new) - 120} more")
        print(
            "\nFix by removing the string. If it is functional rather than promotional "
            "(a converter download source, a notification channel), add the key to "
            "scripts/promotional_allowlist.json with a written reason. Never raise a "
            "baseline count to make this pass."
        )
        return 1
    total = sum(len(v) for v in violations.values())
    backend_total = sum(len(v) for v in backend_violations.values())
    print(
        f"no promotional strings OK: {len(violations)} frontend and browser-surface file(s) carrying "
        f"{total} baselined "
        f"violation(s), {len(backend_violations)} backend file(s) carrying {backend_total}, "
        f"{len(allow)} allowlisted key(s), 0 new"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
