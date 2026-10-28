#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail the build if a proprietary classification leaks into shippable files.

The licensing position is that division NUMBERS are interoperability facts and stay,
while the official division TITLES are the licensor's expression and must never be
bundled. Our own scope wording replaces them (see ``us_pack/config.py``), and users
who hold a licence import the official tables themselves.

Two heads, because the two leaks look nothing alike.

Head 1 catches a code paired with its official title, the shape a reproduced table
takes. Half those titles are ordinary trade words, so a bare match proves nothing:
"03" next to "Concrete" is also how any bill of quantities reads. Two discriminators
separate a copied table from ordinary vocabulary. Correspondence: the number must be
the official number for that exact title, so "07 - Concrete" is a coincidence and is
ignored. Distinctiveness: a multi-word title is language nobody reaches for by
accident and fails on sight, while single-word titles only fail once one file carries
enough distinct divisions to be the compilation rather than a coincidence. Measured
against the tree, a crosswalk to another country's standard peaks at four distinct
divisions while a real reproduced table carries twenty-four or more, so the threshold
between them is wide.

Head 2 catches the standard's name where a user reads it as a description of our own
content. That is a trademark question rather than a copyright one, it appears where no
code sits nearby, and head 1 cannot see it at all. One discriminator does most of the
work: an all-lowercase occurrence is the technical key we exchange over the API and
persist in ``classification_standard``, and it stays untouched, while the capitalised
display form is the brand. Naming the standard is legitimate in a picker, a preset or
a validation rule, so those places are allowlisted by location rather than globally.

Brand-safe by design, like ``check_no_brand_tokens.py``: only SHA-256 of the
normalised titles and brand tokens is stored, never the literal strings, so this gate
does not itself become the bundled copy it exists to prevent. Findings print the
division number and the location, never the matched title.

Exit codes:
    0  no proprietary classification content found
    1  at least one finding (with file:line locations)

Usage::

    python scripts/check_no_proprietary_classification.py                # full tracked tree
    python scripts/check_no_proprietary_classification.py path/a path/b  # given files (pre-commit)

Put ``denylist-ok`` in a trailing comment to allow a deliberate one-off; for a place
that will keep naming the standard, add it to ``_ALLOWED_NOMINATIVE`` instead, which
needs no edit to the file itself.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# SHA-256 of the normalised official division titles, mapped to the division numbers
# that title belongs to and its word count. Normalisation lowercases, reduces runs of
# non-alphanumerics to single spaces and drops the word "and", so punctuation and
# ampersand variants collapse onto one hash. A title shared by two editions carries
# both numbers.
_TITLE_HASHES: dict[str, tuple[str, int]] = {
    "414e515eea42877dee585c1d4a0bd7da7562d412cd014f2d450e51cf229c9f61": ("00", 3),
    "c089bbeb08db8c3f718c9fd98462039c50df8c285c70dabbcc068a9fb16573c9": ("01", 2),
    "a75eb88d5628aabc5514332ebe1bff809b89541a877ef9c09d6bc49dd9438eaf": ("02", 2),
    "f1a7564755096d220d70bd456d330d406e0d86b7907e613f41f934c6161947e1": ("02", 2),
    "ff298e4c4f975caa25114d524167027dd47275f4bf7e414fce87b993ad12d058": ("03", 1),
    "ccf7ace31902ec6087fd74c3e78331042943e314dc121add7762d57ce2760f8d": ("04", 1),
    "a89604ce57440711702f8f68dd4cec888aa48fe1f1155c37b007bece1d4ae1ed": ("05", 1),
    "d8ec903f4283639997f1886b25eeb591c2902546b4b33b9b55ea70a15777f162": ("06", 3),
    "7f8840ba0231d250059a5fdaefa98102b1381d9902267bd5b0a5e69d62228f90": ("06", 2),
    "3fa98f3a012108462f49492c3e311c2950bc7dcacb2481d36a2a51a8c6fa7bc9": ("07", 3),
    "add875e192edf555f22898d640b2e2acd69cd7b84008318423a8d13ee1202464": ("08", 1),
    "3350522872509aebf0730a210ede5cd93d0f7b0cbb3d0057b05cc44080d68761": ("08", 2),
    "37dfcd31511d7a3b725174119fb660a89f995e6aa1577cd6223b75b5c4259e21": ("09", 1),
    "829d5da236a83da03358df965a70747dd1be109cbc150831a601ced0bbdfa09b": ("10", 1),
    "1c09f5a7f47df2ee11dac3abd4010d9b70fb62c46446fd0c872c67a37609a52d": ("11", 1),
    "85f9e39efc1f44b8cec6af1825d62e29b4e3296aca91043a2bd6a0fa7c10b969": ("12", 1),
    "c0aaec039fb99fb424ea35d21e38fc6d1892e011d8287c14c712c7f8d6f60cda": ("13", 2),
    "fd5b317ce51737d92f988c18d341d83d9293bd766ace8352e5040454ab4fafff": ("14", 2),
    "ae46133e1dceb0b28aa816b5a0ca124a3d9ff25b56a4ba21b8ed9cbec6bce82f": ("14", 2),
    "96ae0f875bd9062d5e263473590877f82d65b160571e0d4385c65d9a3e3c081f": ("15", 1),
    "7e23583acb28d1f5294dede068ae3bb0a24be9d4551c5cd6189974ad11cc19a4": ("21", 2),
    "864b24fdae91ef938ba12b344c1652425531133b3194c9114475269e17257c47": ("22", 1),
    "7b629a37d1d0a5523b152f22bc4ba0cef2a8e8a12e03eb6d300d99f014f9d96d": ("23", 5),
    "e775c826f24489c949acff175e1133ca3f368f6d0b686080070c3a642ba94dfc": ("25", 2),
    "ed157486b875d92c25c90df1c09bafd0c9455035a3f800abc513545af7d48e3d": ("16,26", 1),
    "19ec6af8eddb1c0e8811f027ecc93a47c51792412203cf6a6d57e91c0db89212": ("27", 1),
    "6c90cdb0c3d3567dccec0e3a677c8e7b90d800ef937216c1c194190b0b23b718": ("28", 3),
    "697369d238cec0ae36259792f49b3814ccec41b524948fce9621449c00995d3d": ("31", 1),
    "10bd743745c6163b8cf7a80cd45deb4f09fcc84d442a4e148833d3c45e7a604d": ("32", 2),
    "abe2c417d1ddae1e3be903c7733aacf4116eb94109562930886b63538cbf63a5": ("33", 1),
    "0b349c79e44d2b99d730dd75fa754c9e5c9c055bdd78ad07504e4464479d8f5c": ("34", 1),
    "4242dd550dc8c4644518f6581a40bb1acaef32f9e6390363b85891f018e8dc9e": ("35", 3),
    "cdcda500a26a85fc5e3f192b0b25c9cc8b5802a209989d5069010c0edd9af070": ("40", 2),
    "428f7c6f163d775477d5df7b68ac7027d25be2dac4c37dc4f50cbaf7c4753cdf": ("41", 4),
    "2d394602af2350f6e7d8ee2508c776f08a623ce2d669998224a127f3f2bdd024": ("42", 5),
    "00014a9482b226116149e0408ef94589aa408e9f334c329f48ce34d278ce05a4": ("43", 7),
    "f11508b182310976f72d40ee6ccff65bc6b1432bc3f8314f5b067567c802592c": ("44", 4),
    "9404ba9bbfea1ca99292f2cf98a02edc9335c3b59696eea6f30b723a1fb26c1f": ("45", 4),
    "5f11c125c5f4cdcd67f036283c699d8a245302d74152678420b4f7cba1427d51": ("46", 3),
    "26bdb7384bc678ce7bcbbae1c7f09b438dcab25d3ef653ba9a319f584d1258c6": ("48", 3),
}

# SHA-256 of the lowercased names of the proprietary classification families and of
# the commercial cost-data brand. Four entries, one per family, each generated here
# from a known token so nothing in this set is carried on trust.
_BRAND_HASHES: frozenset[str] = frozenset(
    {
        "4a0ff40f13c6ff8ead21e6c2af0b6361a70312a83fa08e41183da87ce0c30cb7",
        "13cc0544e8294374c5222a7cd57a433b236fc429077b8d48759c37526a6e8367",
        "1956a43d6bfedfca8e095b873373075829b220c50cf74393a4467392398be95d",
        "535951eee5c78021bdca282e8c240c4df6c4fcab24a44b86e26799b64b6c9784",
    }
)

# Places that legitimately name a standard, keyed by path so the file itself needs no
# marker comment. A picker has to print the name of the thing being picked, a preset
# is named after the standard it implements, a validation rule says which standard it
# enforces, and a catalogue listing states which classification a data pack
# interoperates with. The value is the set of fields allowed there, so a new field in
# an allowlisted file is still examined.
_ALLOWED_NOMINATIVE: dict[str, frozenset[str]] = {
    # Catalogue and module copy stating which standards a feature interoperates with.
    "backend/app/core/marketplace.py": frozenset({"description"}),
    "backend/app/modules/us_pack/manifest.py": frozenset({"description"}),
    "backend/app/modules/contracts/compliance_packs.py": frozenset({"description"}),
    "frontend/src/modules/regional-exchange/manifest.tsx": frozenset({"description"}),
    # Validation rules are named after the standard whose conformance they check.
    "backend/app/core/validation/rules/__init__.py": frozenset({"name", "description"}),
    "backend/app/modules/validation/manifest.py": frozenset({"description"}),
    "backend/app/modules/validation/rules/bim_model_rule.py": frozenset({"description"}),
    "backend/app/modules/validation/rules/bim_universal.py": frozenset({"description"}),
    # Agents that classify into a standard have to say which ones they can target.
    "backend/app/modules/ai_agents/agents/advisors.py": frozenset({"description"}),
    "backend/app/modules/ai_agents/agents/cost_classifier.py": frozenset({"description"}),
    # API parameter documentation naming the classification a filter accepts.
    "backend/app/modules/assemblies/router.py": frozenset({"description"}),
    # Column-header aliases exist to recognise the name in a customer's spreadsheet.
    "backend/app/modules/eac/aliases/seed_catalog.json": frozenset({"name"}),
    # A whole pack whose job is to name the standards US work interoperates with.
    "packs/us-costdata/": frozenset({"title", "label", "name", "standard", "description"}),
    # Partner pack: naming this supplier's database as the pack's data source is
    # sanctioned under a real partnership agreement, so it is not a finding here and
    # must not be rewritten. An earlier wave read it as an unlicensed claim and
    # rewrote it; the entry exists so that cannot happen a second time.
    "packs/batimatech-ca/": frozenset({"title", "label", "name", "standard", "description"}),
    # Canada country pack. Its catalogue copy (the PyPI description and the pack
    # manifest description) lists the standards the pack interoperates with, the same
    # nominative use as us_pack/manifest.py above. The rule pack is a validation rule
    # set whose id is the standard's key: its name, standard and description say which
    # classification it checks, as a validation rule must. Division titles are still
    # scanned in all three, since only the listed fields are exempt from head 2.
    "packs/canada-ca/pyproject.toml": frozenset({"description"}),
    "packs/canada-ca/src/openconstructionerp_canada_ca/manifest.py": frozenset({"description"}),
    "packs/canada-ca/src/openconstructionerp_canada_ca/rule_packs/masterformat_2020.json": frozenset(
        {"name", "standard", "description"}
    ),
    # Pickers and presets: the user chooses a standard and must see which one.
    "frontend/src/features/ai/QuickEstimatePage.tsx": frozenset({"label"}),
    "frontend/src/features/projects/CreateProjectPage.tsx": frozenset({"label"}),
    "frontend/src/features/boq/CreateBOQPage.tsx": frozenset({"standard"}),
    "frontend/src/features/boq/MarkupPanel.tsx": frozenset({"standard"}),
    "frontend/src/features/boq/presets/index.ts": frozenset({"name", "description"}),
    "frontend/src/features/eac/components/EacBlockPalette.tsx": frozenset({"description"}),
    "frontend/src/modules/regional-exchange/regionalRegistry.ts": frozenset({"label"}),
    # Shipped release notes are a historical record and are not rewritten.
    "frontend/src/features/about/Changelog.tsx": frozenset({"summary"}),
    # Generated inventories that copy descriptions already allowed at their source.
    "frontend/src/features/architecture/architecture_manifest.json": frozenset({"description"}),
    "scripts/_88_module_inventory.json": frozenset({"description"}),
}

# How many distinct single-word correspondences one file may carry before it stops
# looking like coincidence and starts looking like the compilation. Eight sits above
# the largest innocent case measured, a crosswalk to another standard whose own
# vocabulary happens to include words like Concrete and Masonry.
_TABLE_THRESHOLD = 8

# Markdown and TOML are here because a claim about our own content is not confined
# to code. A pack's distribution description lives in ``pyproject.toml`` and its
# product copy in ``README.md``, and both are read by users on PyPI; a pack naming a
# commercial cost database as its data source sat in exactly those two files through
# every green run of this gate. Note the limit of the extension fix: head 2 matches a
# field assignment, so it reads the TOML description but not the same claim written as
# markdown prose, which has no field name to match.
_SCAN_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".sql",
    ".csv",
    ".md",
    ".toml",
}

# Fields a user reads, optionally quoted as a dict or object key, which is the shape
# most of them take. The boundary before the name cannot open after an underscore,
# which is what keeps the interop key ``classification_standard`` out of the match;
# ``validation_rule_sets`` is a bare list and has no field name to match at all.
_FIELD_RX = re.compile(
    r"""["']?\b(?<![\w.])(?P<field>boq_name|budget_boq_name|boq_description|description|standard"""
    r"""|label|title|name|scope|summary|headline)\b["']?\s*[=:]\s*\(?\s*["'](?P<value>[^"']{0,400})["']""",
)

_PAIR_RXS = (
    # "Division 03 - Title", "03 - Title", "03: Title"
    #
    # The title group deliberately admits parentheses and does not require an
    # ASCII capital to open. Both exclusions used to be load-bearing bugs. A
    # bilingual pack writes its sections as "Division 03 - Béton (<english>)":
    # stopping at the parenthesis reads only the French, which is our own text,
    # and never examines the English half, which is where the licensor's title
    # sat; and a title opening on an accented capital, "Division 26 -
    # Électricité (...)", failed to match at all. The title position is now
    # taken whole and taken apart by ``_title_fragments`` below.
    #
    # The gloss is written as a placeholder on purpose. An earlier draft of this
    # comment spelled the English title out, which put a division number beside
    # its official title inside the gate that exists to keep them apart. The
    # census caught it; the gate itself did not, being one division short of its
    # own threshold.
    # Greedy, and with no trailing lookahead: the title class already excludes
    # both quote characters, so it stops at the end of the literal on its own.
    # The lazy-plus-lookahead form this replaces cost a backtrack for every one
    # of up to seventy lengths at every candidate start, which measured five
    # times slower over the tree once the class was widened to admit brackets.
    # Trailing rule characters are dropped in ``_title_fragments`` instead.
    re.compile(r"""(?:Division\s+)?(?P<num>\d{2})\s*[-:|]\s*(?P<title>[^\W\d_][^"'\n]{2,70})"""),
    # {"number": "03", "title": "..."} and {code: '03', label: '...'}
    re.compile(
        r"""["']?(?:number|code|division)["']?\s*:\s*["'](?P<num>\d{2})["']\s*,\s*"""
        r"""["']?(?:title|label|name|scope|description)["']?\s*:\s*["'](?P<title>[^"']{2,70})["']"""
    ),
    # "03": "Title"
    re.compile(r"""["'](?P<num>\d{2})["']\s*:\s*["'](?P<title>[A-Z][^"']{2,70})["']"""),
)

_WORD_RX = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
# Cheap pre-filter for the pair regexes. Any two-digit run used to qualify,
# which is nearly every line of a locale file or a generated manifest. All
# three pair shapes put a separator just after the number, optionally through
# a closing quote, so requiring that skips the bulk of the tree without
# narrowing what can be found.
_TWO_DIGITS_RX = re.compile(r"""\d\d\s*["']?\s*[-:|,]""")

# One title position can carry more than one title. A parenthetical gloss is
# the shape that motivated this: the local-language title sits outside the
# brackets and the English one inside, and only the second is under licence.
# A separator does the same job inside them, a gloss written "(<english> -
# SBC 304)" putting the official title in front of a local code reference.
_PAREN_RX = re.compile(r"\(([^()]{2,80})\)")
_SEP_RX = re.compile(r"\s*(?:[/&,:]|\s[-–—]\s)\s*")
# A comment rules off its heading with box-drawing or dashes, and a greedy
# title swallows them.
_RULE_OFF_RX = re.compile(r"[\s─-╿_=-]+$")


def _title_fragments(title: str) -> Iterator[str]:
    """Yield every candidate title inside one title position, widest first.

    Splitting is safe here because nothing is judged on shape: a fragment is
    only ever a finding if its hash is the official title AND the number beside
    it is that title's own number. Our own scope wording survives being cut at
    its commas for the same reason, which
    ``test_our_own_scope_wording_is_not_on_the_denylist`` asserts against the
    real hash list rather than a synthetic one.
    """
    title = _RULE_OFF_RX.sub("", title).strip()
    if not title:
        return

    # Bracketing and separators compose, so the split has to compose with them.
    # A gloss can hold a title in front of a local code reference, and cutting
    # the whole title at its separators does not reach inside the brackets to
    # find it. Splitting the outer text alone only appeared to work on a pack
    # whose local half is non-Latin, where normalisation dropped that half and
    # left the English standing on its own by accident; the same shape in a
    # Latin-script pack went straight through.
    seen: set[str] = set()
    pending = [title]
    while pending:
        raw = _RULE_OFF_RX.sub("", pending.pop(0)).strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)

        # Yield a bracket-trimmed form but keep the raw one to take apart: a
        # fragment cut at a separator can carry one unmatched bracket, and
        # trimming before extraction destroys the pairing the extractor needs.
        candidate = raw.strip(" ()")
        if candidate:
            yield candidate

        head = raw.split("(")[0].strip()
        if head and head != raw:
            pending.append(head)
        pending.extend(_PAREN_RX.findall(raw))
        parts = [part.strip() for part in _SEP_RX.split(raw)]
        pending.extend(part for part in parts if part and part != raw)


# A line that is nothing but a string literal continues the statement above it, and a
# closing quote sitting against an opening one is implicit concatenation to be spliced.
_CONT_RX = re.compile(r"""\s*["'][^"']*["']\s*[,)\]]?\s*$""")
_SPLICE_RX = re.compile(r"""["']\s*["']""")


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (first line number, joined text) with implicit concatenation spliced.

    A description written as adjacent literals across several lines hides its tail
    from a per-line scan: the field name sits on one line and the brand on the next,
    where no field name is in sight. That is not hypothetical, it is how the source of
    a module description is written, and only the generated single-line copy of that
    same text was being caught.
    """
    raw = text.split("\n")
    index = 0
    total = len(raw)
    while index < total:
        start = index
        parts = [raw[index]]
        # The substring test keeps the regex off the overwhelming majority of lines;
        # generated manifests run to six figures of lines and the difference shows.
        while index + 1 < total and raw[index + 1].lstrip()[:1] in ('"', "'") and _CONT_RX.match(raw[index + 1]):
            index += 1
            parts.append(raw[index].strip())
        line = " ".join(parts) if len(parts) > 1 else parts[0]
        if len(parts) > 1 or '" "' in line or "' '" in line or '""' in line or "''" in line:
            line = _SPLICE_RX.sub("", line)
        yield start + 1, line
        index += 1


def _allowed_fields_for(path: str, allowlist: dict[str, frozenset[str]]) -> frozenset[str]:
    """Look the path up directly, then as a prefix, so a whole pack can be exempted."""
    key = path.replace("\\", "/")
    if key in allowlist:
        return allowlist[key]
    for prefix, fields in allowlist.items():
        if prefix.endswith("/") and key.startswith(prefix):
            return fields
    return frozenset()


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(word for word in text.split() if word != "and")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Finding:
    """One located problem, reported without echoing the matched string."""

    def __init__(self, path: str, line_no: int, head: str, detail: str) -> None:
        self.path = path
        self.line_no = line_no
        self.head = head
        self.detail = detail

    def __str__(self) -> str:
        return f"  {self.path}:{self.line_no}  [{self.head}] {self.detail}"


def scan_text(
    path: str,
    text: str,
    title_hashes: dict[str, tuple[str, int]] | None = None,
    brand_hashes: frozenset[str] | None = None,
    allowed: dict[str, frozenset[str]] | None = None,
) -> list[Finding]:
    """Return the findings for one file's contents.

    The hash maps and the allowlist are injectable so tests can exercise
    correspondence, the table threshold and the nominative exemption with synthetic
    entries, instead of reproducing a proprietary title in the test file to prove the
    gate catches proprietary titles.
    """
    titles = _TITLE_HASHES if title_hashes is None else title_hashes
    brands = _BRAND_HASHES if brand_hashes is None else brand_hashes
    allowlist = _ALLOWED_NOMINATIVE if allowed is None else allowed
    allowed_fields = _allowed_fields_for(path, allowlist)

    findings: list[Finding] = []
    single_word_divisions: dict[str, int] = {}
    reported_pairs: set[tuple[int, str]] = set()

    for line_no, line in _logical_lines(text):
        if "denylist-ok" in line:
            continue

        # Cheap guards first: no two-digit run means no pair can be here, and a line
        # with no assignment or key separator carries no field value.
        for rx in _PAIR_RXS if _TWO_DIGITS_RX.search(line) else ():
            for match in rx.finditer(line):
                num = match.group("num")
                for candidate in _title_fragments(match.group("title")):
                    entry = titles.get(_sha(_norm(candidate)))
                    if entry is None:
                        continue
                    numbers, words = entry
                    if num not in numbers.split(","):
                        continue  # a number that is not this title's own is a coincidence
                    if words > 1:
                        # One title position yields several fragments and more
                        # than one can hash to the same division: a bilingual
                        # string whose other language drops out of the
                        # normalisation matches both whole and parenthetical.
                        # That is one leak, so it is reported once.
                        if (line_no, numbers) in reported_pairs:
                            continue
                        reported_pairs.add((line_no, numbers))
                        findings.append(
                            Finding(
                                path,
                                line_no,
                                "pair",
                                f"official title of division {numbers} (multi-word)",
                            )
                        )
                    else:
                        single_word_divisions.setdefault(numbers, line_no)

        if "=" not in line and ":" not in line:
            continue

        for match in _FIELD_RX.finditer(line):
            field = match.group("field")
            if field in allowed_fields:
                continue
            for word in _WORD_RX.findall(match.group("value")):
                if word == word.lower():
                    continue  # the all-lowercase form is the technical interop key
                if _sha(word.lower()) in brands:
                    findings.append(
                        Finding(
                            path,
                            line_no,
                            "brand",
                            f"standard's name in user-visible field '{field}'",
                        )
                    )
                    break

    if len(single_word_divisions) >= _TABLE_THRESHOLD:
        findings.append(
            Finding(
                path,
                min(single_word_divisions.values()),
                "table",
                f"{len(single_word_divisions)} distinct divisions paired with their official titles",
            )
        )
    return findings


def _tracked_files() -> list[str]:
    """List the tree from the repository root, whatever directory we were called in.

    Without the explicit cwd, ``git ls-files`` answers about the caller's directory and
    returns paths relative to it, which resolve to nothing under the repository root:
    the gate then scans zero files and reports success.
    """
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _resolve(explicit: list[str]) -> tuple[list[str], list[str]]:
    """Turn the arguments into a file list, and name what could not be turned into one.

    A directory used to fall through the ``is_file`` test and be dropped without a
    word, so pointing the gate at a package scanned nothing and still printed OK.
    That is the failure this whole script exists to prevent, sitting in the script:
    a green that means "looked in the wrong place", not "found nothing". Directories
    are expanded here, and anything that resolves to no file at all is returned as
    unresolved rather than silently skipped.
    """
    files: list[str] = []
    unresolved: list[str] = []
    for rel in explicit:
        full = REPO_ROOT / rel
        if full.is_file():
            files.append(rel)
        elif full.is_dir():
            found = sorted(
                child.relative_to(REPO_ROOT).as_posix()
                for child in full.rglob("*")
                if child.is_file() and child.suffix.lower() in _SCAN_SUFFIXES
            )
            if found:
                files.extend(found)
            else:
                unresolved.append(rel)
        else:
            unresolved.append(rel)
    return files, unresolved


def main(argv: list[str]) -> int:
    explicit = argv[1:]
    if explicit:
        paths, unresolved = _resolve(explicit)
        if unresolved:
            # A path that names nothing is a shrinking sweep, not a clean one. A typo in
            # a CI pathspec must fail loudly, or the gate quietly stops guarding what it
            # was pointed at and keeps printing success.
            print(
                "ERROR: these arguments matched no scannable file: " + ", ".join(unresolved),
                file=sys.stderr,
            )
            return 1
    else:
        paths = _tracked_files()

    findings: list[Finding] = []
    scanned = 0
    skipped_by_suffix = 0
    for rel in paths:
        full = REPO_ROOT / rel
        if not full.is_file():
            continue
        if full.suffix.lower() not in _SCAN_SUFFIXES:
            skipped_by_suffix += 1
            continue
        scanned += 1
        findings.extend(scan_text(rel, full.read_text(encoding="utf-8", errors="replace")))

    if not scanned:
        # A sweep that reached nothing is not a clean sweep. Saying "OK" here is how a
        # gate goes green for years without ever having read the tree it guards. This
        # holds for an explicit selection too: every argument being a file type we do
        # not scan is a fact worth printing, not a pass to hand back.
        where = "the whole tree" if not explicit else "the given paths"
        print(
            f"ERROR: asked to scan {where} and found no files to scan"
            + (f" ({skipped_by_suffix} skipped by file type)" if skipped_by_suffix else ""),
            file=sys.stderr,
        )
        return 1

    if findings:
        print(
            f"ERROR: proprietary classification content found ({len(findings)}):",
            file=sys.stderr,
        )
        for finding in findings:
            print(str(finding), file=sys.stderr)
        print(
            "\nDivision numbers are fine to keep. Replace the official titles with our own "
            "scope wording from backend/app/modules/us_pack/config.py, and describe the "
            "classification by category in anything a user reads. A place that has to keep "
            "naming the standard belongs in _ALLOWED_NOMINATIVE in this script.",
            file=sys.stderr,
        )
        return 1

    print(f"classification denylist OK: {scanned} files scanned, no proprietary titles or brand strings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
