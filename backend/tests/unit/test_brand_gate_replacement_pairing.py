"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The rule that lets the de-brand code name the things it is de-branding.

A gate that asks only whether a forbidden name is present convicts the three
files that exist to remove it. ``app.modules.formwork.debrand`` holds the old
catalogue names because the repair needs them as search keys, the frozen
revision that renames the same rows holds them for the same reason, and the
migration round-trip test seeds them so that it has something to prove was
renamed. Those files are about the names. Any other file that carries one is
using it.

The usual way to tell those apart is a list of blessed paths, and that list is
how a gate dies. It grows by one every time somebody is blocked, nobody
re-reads it, and after a while the list decides what ships instead of the rule.
So the gate draws the line on a property of the file's own content: a file that
renames a thing has to say what it renames it to, and a file that merely
mentions it has no reason to. A denied token is passed over only where the plain
descriptor it is renamed to also appears, and only for that one pairing.

The load-bearing test here is the second one. The first shows the three subject
files scanning clean, and on its own that means nothing at all - a gate that had
stopped detecting these tokens entirely would pass it just as well. The second
takes the pairing away and requires the same three files to be convicted, which
is what makes the first one evidence. That is also the shape of the ordinary
file the rule has to catch, expressed in real content rather than an invented
line: identical text, minus the fact that it states the replacement.

Nothing in this file spells a brand out. The real-tree tests read the tokens
from the repository, and the mechanism tests use invented ones, so this file
cannot become the leak it is guarding against.
"""

from __future__ import annotations

import hashlib
import importlib.util
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_no_brand_tokens.py"

# The three files that carry the old catalogue names legitimately. Named here
# rather than discovered, because the point of the check is that these specific
# files stay readable to the gate as it changes.
SUBJECT_FILES = (
    REPO_ROOT / "backend" / "app" / "modules" / "formwork" / "debrand.py",
    REPO_ROOT / "backend" / "alembic" / "versions" / "v3271_formwork_debrand.py",
    REPO_ROOT / "backend" / "tests" / "integration" / "test_migrations_roundtrip.py",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("check_no_brand_tokens", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load_script()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("path", SUBJECT_FILES, ids=lambda p: p.name)
def test_a_file_that_states_the_replacement_is_spared(gate, path: Path) -> None:
    assert path.is_file(), f"{path} is missing; the de-brand no longer looks as this assumes"
    assert gate._scan_file(path) == []


@pytest.mark.parametrize("path", SUBJECT_FILES, ids=lambda p: p.name)
def test_and_it_is_the_pairing_that_spares_it(gate, monkeypatch, path: Path) -> None:
    """Take the pairing away and the same file has to be convicted.

    Without this, the test above is satisfied by a gate that has quietly stopped
    recognising these tokens at all, which is the failure it exists to rule out.
    """
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {})
    hits = gate._scan_file(path)
    assert hits, f"{path.name} produced no hit with the pairing removed, so sparing it proves nothing"


def test_the_rule_is_per_pairing_and_not_per_file(gate, monkeypatch, tmp_path: Path) -> None:
    """One file, two denied names: the one it renames passes, the other does not.

    A file earns nothing for the names it is not renaming. Were this per file,
    stating one replacement would license every other name in the same file,
    which is a blanket exemption with extra steps.
    """
    renamed, mentioned = "qwrtled", "zbxfoop"
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest(renamed), _digest(mentioned)}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {_digest(renamed): (3, _digest("plain neutral descriptor"))})

    target = tmp_path / "sample.py"
    target.write_text(
        f'RENAMES = (("{renamed}", "Plain neutral descriptor"),)\n# see also the {mentioned} range\n',
        encoding="utf-8",
    )

    reported = [line for line, _, _ in gate._scan_file(target)]
    assert reported == [2], f"expected only the mentioned name on line 2, got {reported}"


def test_the_replacement_may_be_worded_and_wrapped_differently(gate, monkeypatch, tmp_path: Path) -> None:
    """Both sides are reduced the same way, so punctuation and line breaks cannot defeat it.

    A descriptor is written with a hyphen in one file and without in another, and
    a long one wraps across two lines in source. If the comparison were literal,
    the gate would convict a file that is doing the rename correctly, and the
    first person to hit that would reach for a path exemption.
    """
    token = "qwrtled"
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest(token)}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {_digest(token): (4, _digest("single side tie panel"))})

    target = tmp_path / "wrapped.py"
    target.write_text(
        f'RENAMES = (("{token}",\n    "Single-side\n    tie panel"),)\n',
        encoding="utf-8",
    )
    assert gate._scan_file(target) == []


def test_an_escaped_newline_inside_the_descriptor_defeats_the_pairing(gate, monkeypatch, tmp_path: Path) -> None:
    """The limit of the reduction, measured rather than assumed.

    A real line break disappears, because it is not a letter or a digit. A
    backslash-n written inside a string literal does not: the tokenizer sees the
    letter, so the descriptor gains a word in the middle and stops matching. It
    is left this way rather than special-cased, on two grounds. The descriptors
    are written as plain one-line literals wherever the rename is actually done,
    so nothing real hits it; and the failure runs in the safe direction, since a
    file whose descriptor is not recognised is reported rather than permitted.
    Somebody who eventually writes one across an escape will see a conviction on
    a file that looks correct, and this test is the answer to why.
    """
    token = "qwrtled"
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest(token)}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {_digest(token): (4, _digest("single side tie panel"))})

    target = tmp_path / "escaped.json"
    target.write_text(f'{{"old": "{token}", "new": "Single-side\\ntie panel"}}\n', encoding="utf-8")
    assert [line for line, _, _ in gate._scan_file(target)] == [1]


def test_a_four_letter_entry_can_actually_fire(gate, monkeypatch, tmp_path: Path) -> None:
    """The length bound must not silently disarm the shortest entries.

    This is a regression test for a real one. A four-letter name sat in the
    denylist while the lower bound was five, so it was never once compared
    against anything: the gate reported clean over a tree that named it in
    shipped documentation, and the entry read as coverage while forbidding
    nothing. Raising the bound again would recreate that exactly, and nothing
    else in the suite would notice.
    """
    short = "qwrt"
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest(short)}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {})

    target = tmp_path / "short.md"
    target.write_text(f"Regional sources: {short}, and others.\n", encoding="utf-8")
    assert [line for line, _, _ in gate._scan_file(target)] == [1]


def test_every_pairing_names_a_token_the_gate_actually_denies(gate) -> None:
    """A pairing for a token that is not denied is dead configuration.

    It would look like an exemption being maintained while permitting something
    that was never forbidden, which is the kind of entry that survives a review
    because it appears to be doing work.
    """
    orphans = [key for key in gate._REPLACEMENT_OF if key not in gate._DENY_HASHES]
    assert not orphans, f"{len(orphans)} pairing(s) name a token that is not on the denylist"


# Entries that no other test in this file protects. The pairing-consistency test
# above covers every token that has a replacement, because removing one of those
# from the denylist leaves its pairing orphaned and that test goes red. These do
# not have a pairing, so nothing was watching them: they are product-line names
# that appear nowhere in our own code and only ever arrive in third-party pack
# data, which is precisely the pressure under which somebody shortens a list.
#
# Hashes, not names, so this file still spells no brand out. Recover which token
# a line refers to the same way the gate does, by hashing the candidate.
_MUST_REMAIN = (
    "ec4188114ad20f506af05aea2ea67489c954672b82be22b256115ce744c2f718",
    "3e86e0d516fafa37db2207120cbdde8d221a292c125f7cc1ab4b55490ca75bb1",
    "3bc87656ead9ecede45114b0463fbd44dbba1eb7ab717af447db4763a70b8b71",
    "7e11a130e9befa6c0d8c5655449d4ccd035d193053e84f6a5b89b7f68bb2e401",
    "8bcd3837a4469ff20ab81a94a4438c2e2032bdecb992a36281f05cf3ebd1f7cc",
    "fb6061067f2f48fe42db037321556e2c2ecee66c56b75ce935523d51bae05565",
)

# The size of the list on the day the guard was written.
_DENY_FLOOR = 82


def test_the_denylist_cannot_quietly_shrink(gate) -> None:
    """A gate whose list can get shorter is a gate that deletes itself.

    This is the real guard of the two below it. It names the entries that have
    to survive, so it stays red when somebody removes one and adds another in
    the same edit, which is the change a bare count cannot see. Adding entries
    is free; that is the direction the list is supposed to move.

    If one of these ever has to go, the argument belongs in the commit that
    deletes the line from here, where a reviewer reads it, rather than in a
    silent edit to the script.
    """
    missing = [digest for digest in _MUST_REMAIN if digest not in gate._DENY_HASHES]
    assert not missing, (
        f"{len(missing)} pinned entr(y/ies) have been dropped from the denylist; "
        "removing one is a decision that has to be argued for, not a side effect"
    )


def test_the_denylist_has_not_lost_entries_in_bulk(gate) -> None:
    """The cruder of the two nets, and the weaker one.

    It catches a wholesale truncation that happens to spare every pinned entry.
    It does not catch a targeted removal, so raising or lowering this number is
    not a way of handling a failure of the test above it.
    """
    assert len(gate._DENY_HASHES) >= _DENY_FLOOR, (
        f"denylist holds {len(gate._DENY_HASHES)} entries, below the floor of {_DENY_FLOOR}"
    )


# The tokeniser's own properties. Until 2026-08-24 a run ended at every
# character outside a to z and 0 to 9, which cut an accented word into pieces.
# That is not a cosmetic bug in a gate that compares runs against a list: the
# pieces are what somebody records. One entry in the denylist had been recorded
# as the fragment left after the mark was dropped, so repairing the tokeniser
# would have disarmed it while every signal stayed green, and another had been
# recorded whole and could never match anything at all. The tests below pin the
# properties that stop either from happening again.
#
# Invented names throughout. The shape of the word is the subject, not the word,
# so this file still spells no brand out.
_FOLDED_NAMES = ("qwortled", "zbxfoop", "qwrtled")
_MARKED_NAMES = ("qwörtled", "zbxfoöp", "qwrtlëd")


@pytest.mark.parametrize("form", ["NFC", "NFD"])
@pytest.mark.parametrize(("marked", "folded"), list(zip(_MARKED_NAMES, _FOLDED_NAMES, strict=True)))
def test_a_marked_name_is_one_run_and_folds_to_its_base_letters(gate, marked: str, folded: str, form: str) -> None:
    """One word has to produce one run, whichever way the text is stored.

    Both spellings matter. Composed text carries the mark inside the letter and
    decomposed text carries it as a character of its own, and the second is the
    one that looks harmless: a run pattern that merely admits letters would end
    the run on the mark and cut the word in two exactly as before. Some tracked
    files are stored decomposed, so this is not a theoretical form.
    """
    runs = gate._tokens(unicodedata.normalize(form, marked))
    assert runs == [folded], f"the {form} spelling produced {runs}, expected one folded run"


def test_a_name_written_with_its_mark_reaches_the_denylist(gate, monkeypatch, tmp_path) -> None:
    """The failure that made the change necessary, as a test.

    A name recorded in the list in its plain form used to be unreachable when it
    was written the way its owner writes it, because the mark ended the run
    before the name was complete, and the gate returned clean on a line naming
    it. Every spelling below has to be caught, including the full-width one,
    which is otherwise a way of writing Latin letters that no ASCII run sees.
    """
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest("qwortled")}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {})
    spellings = {
        "composed": unicodedata.normalize("NFC", "qwörtled"),
        "decomposed": unicodedata.normalize("NFD", "qwörtled"),
        "plain": "qwortled",
        "full_width": "ｑｗｏｒｔｌｅｄ",
    }
    for label, spelling in spellings.items():
        target = tmp_path / f"{label}.md"
        target.write_text(f"Subcontractor: {spelling} and partners.", encoding="utf-8")
        assert [line for line, _, _ in gate._scan_file(target)] == [1], f"the {label} spelling was not caught"


def test_folding_does_not_convict_an_ordinary_accented_word(gate, monkeypatch, tmp_path) -> None:
    """The negative control, and the direction the change had to be safe in.

    Joining runs that the old tokeniser split makes words longer, never shorter,
    so it cannot manufacture a short fragment that collides with an entry. This
    states that as a test rather than as an argument: the entry below is exactly
    the fragment the old tokeniser would have produced from the word in the
    file, and the word has to stay clean anyway.
    """
    monkeypatch.setattr(gate, "_DENY_HASHES", frozenset({_digest("qwor")}))
    monkeypatch.setattr(gate, "_REPLACEMENT_OF", {})
    target = tmp_path / "prose.md"
    target.write_text("Documentation: qwörtled appears here as ordinary prose.", encoding="utf-8")
    assert gate._scan_file(target) == [], "an ordinary accented word was convicted by its own fragment"


def test_an_underscore_still_separates_the_parts_of_an_identifier(gate) -> None:
    """A snake_case name has to keep coming apart.

    The run pattern admits letters and digits in any script, and the underscore
    is excluded on purpose. Were it admitted, a long identifier would become one
    run, most of them would fall outside the length bounds, and the check would
    stop looking at identifiers at all without anything going red.
    """
    assert gate._tokens("qwrt_led_panel") == ["qwrt", "led", "panel"]


@pytest.mark.parametrize(
    ("path", "distinct"),
    list(zip(SUBJECT_FILES, (10, 10, 5), strict=True)),
    ids=lambda value: value.name if isinstance(value, Path) else str(value),
)
def test_the_subject_files_still_reach_every_entry_they_used_to(gate, path: Path, distinct: int) -> None:
    """The census, enforced rather than performed.

    Running the old and the new tokeniser over the tree and comparing what each
    detects is what caught the entry recorded in its broken form. Done by hand
    that protects one commit. Pinned here it protects the next one: these three
    files carry the old catalogue names deliberately, so the number of distinct
    entries they reach measures how much of the list the tokeniser can still
    produce, and a change that disarms one drops the count.

    The scope is honest about itself. Only entries that some file actually
    spells can be counted, because the list holds hashes and a hash cannot be
    read back, so this watches the entries in use rather than all of them.
    """
    tokens = {
        token
        for token in gate._tokens(path.read_text(encoding="utf-8"))
        if gate._MIN_LEN <= len(token) <= gate._MAX_LEN and _digest(token) in gate._DENY_HASHES
    }
    assert len(tokens) == distinct, (
        f"{path.name} reaches {len(tokens)} denied entr(y/ies), expected {distinct}; "
        "an entry has been disarmed, recorded in a form the tokeniser cannot produce, or removed"
    )
    unstable = sorted(token for token in tokens if gate._tokens(token) != [token])
    assert not unstable, (
        f"{len(unstable)} entr(y/ies) do not survive being tokenised again, so they are "
        "recorded in a form the tokeniser no longer produces"
    )
