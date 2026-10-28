"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Demo seed data must not name real trading companies or design practices.

``scripts/check_no_brand_tokens.py`` is the repo-wide gate for this, and it
deliberately cannot express three kinds of name. Its docstring states the
constraint it is protecting: the gate must never fire on an unrelated word, so
tokens that are also ordinary English are left out and handled by review. On top
of that it has a five character floor, and it hashes one maximal ``[a-z0-9]+``
run at a time, so it has no way to describe a brand that is two ordinary words
side by side.

Real firms reached users through exactly those three holes. A four letter
contractor name is under the floor. A practice whose name is also an English
verb is in the excluded class. A developer named after a London dock is two
common nouns. All three shipped in every wheel up to 14.2.1, in
``app/scripts/seed_demo_4d5d.py`` and ``app/scripts/seed_demo_estimates.py``,
because the demo sweep that cleaned ``core/demo_packs`` never reached the
sibling ``app/scripts`` directory.

This test closes those holes without weakening the repo-wide gate, by narrowing
the surface instead of the pattern. It reads only demo seed sources, so a token
that would be ambiguous across the whole repository is far less ambiguous here.
That is what lets the floor drop to four characters and lets ordinary words and
two-word phrases be named.

**The surface is narrow, not prose-free, and the difference matters when you
add a hash.** Contact and bidder rows are the shape this test was built for, but
``core/demo_packs`` also holds hand-authored BOQ tables carrying position
descriptions, tax notes and scope text, which is prose by any measure. Twenty
six of those thirty one packs are excluded from ``ruff format`` for exactly that
reason, see ``[tool.ruff.format]`` in ``pyproject.toml``. Measured 2026-08-03
across the 74 scanned files: 132 397 tokens inside the length window and 144 427
adjacent word pairs, of which the packs contribute 61 801 pairs. So an ordinary
English word, or two ordinary words that also read as a sentence fragment, has a
real chance of appearing here innocently.

That is a cost to pay knowingly rather than a reason to drop the packs. The one
real firm this test's denylist has caught in shipped data, a contractor in a
sitework tender, was in ``demo_packs/condo-toronto.py``. Dropping the packs
would remove the highest-yield surface to protect against a failure that is
loud, located and one line to fix.

Before adding a hash for anything that is also ordinary English, grep the
lowercased string across the scanned set and confirm it does not already occur
as text. A hash that fires on a BOQ description is a false positive nobody can
diagnose, because the literal is not in the file to compare against.

**Two further shapes were unrecordable until 2026-08-06, and one of them had
already leaked.** Both regexes below are ASCII: ``[a-z0-9]+`` and ``[a-z]+``
yield *nothing at all* on a Chinese, Japanese or Korean name, and nothing usable
on a Turkish one, because ``ı`` and ``ş`` are outside the class. So a state
contractor written in Han characters could be deleted from the data but not
remembered, which is the exact failure the denylist exists to prevent. CJK also
has no spaces, so a wider tokeniser is not the answer. ``_DENY_SUBSTRINGS``
tests containment inside each run of such a script instead. Containment is the
blunt instrument here and is used deliberately: a four character Han sequence is
far less likely to occur innocently than an English word, and the one near miss
we know of is real, so read the note on that set before adding to it.

A Latin-script name that carries an accent, a dotless i or a dotted capital I
is shredded by the same two ASCII regexes and belongs in the token or phrase
set, hashed as the fragment the regex actually yields rather than as the name a
reader sees. Three are recorded that way below. Print the ``findall`` output
before you hash anything of that shape, or the entry will be green forever.

**The surface also now includes the locale example values.** A placeholder's
whole job is to show a plausible example, which is how a national contractor
gets typed into one. Nothing had ever checked those files: they held live firms
in fourteen languages, including a Fortune Global 500 state contractor and two
national champions, until 2026-08-06. Only lines carrying a ``_placeholder`` key
are read, not whole locale files, which keeps the prose out.

Brand-safe by the same construction as the gate: only SHA-256 of the lowercased
token or phrase is stored, never the literal string, so this file does not put a
brand name in the repo and does not itself trip the repo-wide gate.

To extend, add a hash::

    python -c "import hashlib;print(hashlib.sha256(b'<lowercased>').hexdigest())"
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"

# Real contractors, consultancies, materials producers and design practices that
# have appeared in demo data. Hashes only, one lowercased token each.
_DENY_TOKENS: frozenset[str] = frozenset(
    {
        "4e44ac61bc0519ecccc8ae9c2dae453f13ca786a647087c7a2266a6ec5232c94",
        "09c7945dc8a40843b498d79e60716cf57772480d518db5afbbd2d6ab880826fa",
        "480a07f18d2fdbf6a82e04e94e02c32f3a9488c4f317c24a4c13619b9572b30b",
        "814c02272c6b9021e615b6b50b4fce0b3f5197fd870585c3bb661bc0158ff7d0",
        "5fdde7b0e721c43a4bc5c3a34e960a047a4809b34a900a8a88912deb4bf1902a",
        "6bc6bf03af18e61486d26f7d92439715ba438be7ac7911d387eadbfc53e795d8",
        "2b171c81fb670e258f432925425cbc28ae815992baece4fd6dec6172c648f20e",
        "17c3a324486be8f84436b3835df56de14c8928f73504319e93c018e6fbd0205b",
        "b4d969421ab34a7895fc58810b7f1ffc93520b10c9cc6c403ca607b9f29f8c04",
        "ad05969625c093458a9e1df667770ccf71a19b58159126854bd4bda44f0fdaba",
        "c2b9f8fa621a7daaec397af14d827f0c017f3f83b4a58bc73cd313af40f79ad2",
        "5fda8083a1784f7ebb246f2d52001eaaf75e1ce06437f297e12b5e5843659f81",
        "ebd3ce5ea305e181fa74e0d21e700c5ad851651396637f621160e149b1d61cc3",
        "20613c35da218fd86e0f18d6b736cbc2b2b037ed4acfd37e1517cd0983118b85",
        "0ec1e6a8c587e38297c7a7fcf2face9abacf9a9bbd28b57f68d046bfbd5b95cf",
        "20920c3de23ff769ee1c1113c409113c10f7c9d752b55660c3e6b8137589e66a",
        "fda1bdcc3e8d94633b84d1ec2277cb3400d298a431259af0d46479732d98c15d",
        "8ee321501d985290acf5cc0e140ec72a524877e15a6a561c3be997a0ea1a407a",
        "f38f6d7164bf334b3282eda983dcb8d5b69e2e14ffa7b4a83532d61aa7ee03be",
        "52fdaf64a84889c55cc04e5337c0afaabe225a9643385b411fdf2082dfac3208",
        "463d049002ce9578dab985b8969b96b7698948206d8ada916bf2676863316dab",
        "e3c7e82d53a1ce84c284f43915a66bf147c75b2a8baf3f2d476bd2ecd754590c",
        "65266ec0e12375d08a468a83da9d63a57eaaa9a24c3e5cd055ad706598310752",
        # The two halves of one coined-looking pair. Neither was on any list
        # while it shipped, because the pair was searched as a phrase and a
        # coined pair is unique by construction, so the query came back empty.
        # Searched apart, each half is a live contractor. Removing them from the
        # data is not the same as remembering them, which is what these are for.
        "467813f7cf203871621e08b72ee4c210215b1f6a4af0e27da53a3cb490fe8bdf",
        "e186dc4cc7fad46dc412de303e24ee681bfe746267c6488d4af0267122f9f6d7",
        # Two ordinary words that are also busy construction brands: a bird
        # several UK builders are named after, and a green-industry compound a
        # live landscaping firm trades under. Both stay here rather than in the
        # repo-wide gate, which promises never to fire on an ordinary word.
        # Checked before hashing, per the note above: neither occurs as text
        # anywhere in the repository. One near miss, a coined name that starts
        # with the bird, is safe only because the rule hashes maximal runs and
        # so reads it as a single longer token.
        "07f15cde5b181425db8524becd96263d600c9652c7de5b89fe1a644f8fd0724b",
        "620380dbf70857c10410a5aa1a6ac0c343ad530e43080b2a1a83f96d0241b458",
        # A common German surname that is also a Nobel laureate, trading in two
        # live German electrical firms. Ordinary as a word, so it belongs here
        # and not in the repo-wide gate. Zero occurrences as text before hashing.
        "f287584e344fdf74b2f2a6c62fdc5e23fe7a4bbc40f61bf1ada6c7b5667ee39b",
        # Five contractors and developers a reviewer read off screen while
        # capturing marketing shots, on four continents. They were gone from the
        # tree by then, removed by the sweeps this file records, but a name that
        # is only removed is a name the next pass can invent again, so each is
        # here as well. The halves that carry the identity are hashed alone
        # where the second word is a surname that cannot stand by itself.
        "fc385a1210474241a05007943c6111fa8ee78eaf8765cc23a6f35f07065db086",
        "dbb47270076c0fb304ad90d46f31bbad91dbe9275e56517310e5a50d00193ab3",
        "4c1e0de9b5b89e92cecaf213cb9cd72923a820edac4797cfe35e0547e1131805",
        "b3db02059179bdb9d8b78de0f423428110e36a1a42dd270e026c956ca9826433",
        "92e1ee69bd5d93f60e201e4da1c68d46366d67e58d9eaad511bdc0f4a9e8cdd6",
        # Three more from the same capture, a general contractor, a builder and
        # a structural practice, all trading in one city.
        "8aea74e8812c1c733f08fee2c0a767d37b3a34602f9f24ec37ed098b78b5363f",
        "5904ed1211e51b072458499a8031778bea56ad78d7dd4ca2f2185835bcfc43b1",
        "c0bf3d1f8a3f750e104c88793b97902b47e42730acc187c5e4a472327485f97d",
        # Two national champions that stood in the locale example values: the
        # largest contractor in one country and a top-tier builder in another.
        "a7629df3ae8e74a89b5c90838f9591c896030aba289fcb4dc077b2f0f5bb5149",
        "f2f40ed74d5ca6c42916c38dc13ec23703253982d228572e2137b5c46ad46716",
        # Candidates rejected while inventing the replacements, not names that
        # ever shipped. The first is a live architecture practice in the country
        # whose locale it was drafted for; the second differs from a live
        # builder in the same country and sector by one suffix. Both read as
        # coined, which is the whole reason they are written down.
        "2f8cc6e2529b2ec0d52dd4e4b73938896ecf159e5ce3596f8a79f87ca262117a",
        "0d671446b54651fcf674c879cf8cff12dd6f5ccf0018f8982fb465f03dceb237",
        # A third rejected candidate, which turned out to be a real village: the
        # place-name hazard the two city nicknames in _DENY_PHRASES record. It
        # is hashed as the leading fragment, not the whole word, because its
        # last two characters are an accented vowel and the ``n`` after it, and
        # ``_TOKEN_RE`` cuts the word there. Hashing what the name looks like
        # would never have matched; hash what the regex above actually yields.
        "c76db1f9a9820fa21d2770ea46217fcb74f7efef7b6eaeeae7166bc8ebabefa6",
    }
)

# Brands that are two ordinary words in sequence. No single-token rule can
# describe these, which is why the repo-wide gate is blind to them. The last
# two are regional nicknames a city's contractors name themselves after, so
# several live firms answer to each. They read as invented until searched, and
# they were waved through on exactly that impression once already.
_DENY_PHRASES: frozenset[str] = frozenset(
    {
        "d1f9da0816d42c1c8a7d06f4985fef19ef93f9e79fe864157c80537aca5099c3",
        "0085aae38d1d88ead679bc7fedd28c1c2d3f9eccde2c7977579773aef6fe2756",
        "08f91c27a450f7e3eb316c94c85622de10b70e96f2fd10ae1cc7443997b275a2",
        # A German trade word followed by one of the commonest German surnames.
        # Three live landscaping firms answer to it at once, on three separate
        # domains. Neither half is usable alone: the trade word appears in any
        # German landscaping scope text, and the surname is a surname.
        "f5ef7f65c238d5fe6a243a1cb1be422660c3a91796cbabdd89508a1ce7bf7267",
        # An aspirational noun plus a sector word. Not one firm but a naming
        # habit: at least seven live US builders use the noun, in Idaho, Arizona,
        # Florida and elsewhere. Same shape as the two city nicknames above.
        "9165db8ddc7ca57acd827ab786923008a2fc9621f8ba168c6165ebd23cd825bc",
        # The two conglomerates a reviewer read off screen whose names are two
        # words. Note the ampersand in the first: ``_WORD_RE`` drops it, so the
        # pair to hash is the two words with a single space and nothing else.
        # Hashing the literal as it appears on screen would never have matched.
        "463ae71b0f3883252452960c1d408f2d593382582209e9e8686af7781070a54d",
        "c7f441f5be3c245ed94063c5c5c95082a90b68418402b84ee352467491058176",
        # Surname plus trade word, the commonest company name on earth and the
        # shape that filled the locale example values. Each of these is several
        # live firms at once, not one: the German pair alone answers to at least
        # six builders. Neither half is usable alone, which is what puts them
        # here: the surnames are surnames and the trade words are trade words.
        "ad90eb71f9fc2916996ab3e82bd4c499635320eb4fd15641ae454cc62ecd4951",
        "e95ab78b906ed39510503cedf7236f359fe4176dcfd8b3030b8bffe639bbe64b",
        "31a097eb323fcd61e239a448ccb50a1eebf3eede48d9b65f3736d3245da7cfd1",
        "54e547fb25f2b66019eeaa1273a4e5bc7f38d7f3bc28b610c243c9637c37bca1",
        "c0fb35e2c37633f084af01a1f6a80890f9747c6086d663737deaf2853a38744c",
        # A trade word plus a capital city. Same class as the two city nicknames
        # above and it was a locale example value, so several live firms match.
        "266bd7ac7ae71696d9ccd454186a318a1204b80307b136e88cab3a8fe89aab7e",
        # An initialism plus a sector word, a live general contractor.
        "fff041bb416a550d4bb1e1d03937237b8bbb030dee8089fb238e8ef96b11c0f8",
        # Three names the ASCII rules can only see in pieces, hashed as the
        # pieces rather than as the name. A Spanish builder whose surname
        # carries an accent that splits it, so the pair is the trade word plus
        # the fragment before the accent. A Dutch builder whose name is three
        # words, caught on its first two, because its last two are a particle
        # and one of the commonest surnames in the country and would fire on
        # anybody. And a Turkish contractor, below.
        "221d0e10c660b77f073de9ce6376163902cd1ede351c923318576a6f0bc1e561",
        "a06520194f8fe87b83bf15e7f1bfd49aa556085d452ff377a0cdafbba01c7ac3",
        # The Turkish one is the sharpest illustration of why the literal is
        # never what you hash. Lowercasing its dotted capital I yields two
        # codepoints, and its dotless i and cedilla s are outside ``[a-z]``, so
        # the regex above shreds "<surname> <trade word>" into five fragments.
        # The pair hashed here is the tail of the surname followed by the head
        # of the trade word, which is the only piece that identifies the firm.
        # The surname alone is deliberately absent: it is the commonest surname
        # in the country and it is already the person-name example in the same
        # locale file, so hashing it would fail on an innocent line forever.
        "71253a7a61aa4b069721a77153b93716658c09c52b5f1b23f011f0b40451705e",
    }
)

# Names written in a script that does not put spaces between words, which
# neither rule above can express because both are ASCII. ``_TOKEN_RE`` and
# ``_WORD_RE`` return nothing whatsoever on a Han, Hangul or Devanagari name,
# so before this set existed a Chinese state contractor could be deleted from
# the data but not remembered.
#
# Matching is containment, restricted to maximal runs of these scripts for
# cost: a run is a handful of characters and there are few of them, whereas
# sliding every window of every length over every line is tens of millions of
# hashes. The guard against a false positive is the length of the entry, not
# the mechanism, and there is a live near miss already. The two leading
# characters of the Chinese entries also occur inside an ordinary phrase
# meaning "of which the building works", in ``zh.ts`` and in a Shanghai cost
# catalogue. That is why every entry is a whole name of four characters or
# more and never a two character prefix. Do not shorten one.
#
# Each entry carries the character length of the name it hashes, because the
# scanner cannot read a length off a hash and has to be told how wide a window
# to cut. Carrying it per entry rather than as a separate list is deliberate:
# a hand kept list of lengths would let someone add a five character name,
# forget the list, and leave the entry green forever with no test able to see
# it, which is the exact failure this file exists to prevent.
_DENY_SUBSTRINGS: frozenset[tuple[int, str]] = frozenset(
    {
        # Three Chinese state contractors seeded into a Shanghai demo pack, plus
        # the sibling bureau that stood in the Chinese locale example. The one
        # in the example is a subsidiary of a Fortune Global 500 group.
        (4, "39b6b02d8502f87ab91c74ef84be6cc56d1710e5b1eeb1f6969ae3c2c0f36fc6"),
        (4, "17287e3ba25dc05ec91d86db07bab885260519557c4957d4b3bf818e9dac97cf"),
        (4, "4ee7e855e21b1aae57c25c5cdf7e0d7a5c786e3399cb038428af4b08106bfe56"),
        (7, "1a26f16dd9bc1cb7c22011d10f3d8801e11f8a8f9ff291a431fe4de72e7bc55a"),
        # A Japanese builder and a Korean one, each of which is several live
        # firms rather than one, both from locale example values.
        (4, "27cb38ac7b8ddb7aa77f84879ec2d0954687ee9aa57ec002d9ced0d8696a15ad"),
        (6, "14f2273c16e2949c5385c3c9431cb4abc1de5cd71d38e108270df449216be696"),
        # The distinctive first word of an Indian group, from the same place.
        # The trade word after it is dropped: a space would split the run.
        (7, "669d30a532ec468ca550e00d83d6c8ec4b3dd3fc69e94e942a2dbc459248ddd0"),
        # Coined as the Japanese replacement and then rejected: the two
        # character stem is a live Tokyo corporation in the national company
        # register, trading in another sector under the same reading.
        (4, "96583bcfd8a896f66d396645116e44c5eb2bdff3c3fddac532cc03d2acfcc91e"),
    }
)

# Derived, never written by hand, so an entry cannot be added at a width the
# scanner does not cut.
_SUBSTRING_LENGTHS = tuple(sorted({length for length, _ in _DENY_SUBSTRINGS}))


# Scripts that do not separate words with spaces, so a name in them has to be
# matched by containment rather than by tokens. Arabic and Hebrew are absent on
# purpose: they do space their words, so a name in them wants the phrase rule,
# and the phrase rule is ASCII. A name in either script is unrecordable by any
# set in this file today.
def _is_scriptio_continua(char: str) -> bool:
    code = ord(char)
    return (
        0x0900 <= code <= 0x097F  # Devanagari
        or 0x0E00 <= code <= 0x0E7F  # Thai
        or 0x3040 <= code <= 0x30FF  # Hiragana and Katakana
        or 0x3400 <= code <= 0x4DBF  # Han, extension A
        or 0x4E00 <= code <= 0x9FFF  # Han
        or 0xAC00 <= code <= 0xD7AF  # Hangul syllables
    )


# One collision found in this sweep is deliberately absent from both sets. A
# four letter English noun that is also a surname turned up as a one-man
# groundworks contractor and as a registered company, so the demo name carrying
# it was rewritten. The token itself stays off the list: it is ordinary HVAC
# vocabulary, it would fire on a fan or damper description in the pack BOQ
# tables, and a hash that fires on prose is the false positive the docstring
# above warns about. Rewriting the datum is the whole remedy here.

# Four, not five: the shortest name that reached users was four characters, and
# the repo-wide gate's floor is the reason nothing saw it.
_MIN_LEN = 4
_MAX_LEN = 16
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_WORD_RE = re.compile(r"[a-z]+")


def _seed_sources() -> list[Path]:
    """Every source that writes demo records a user can read on screen.

    The set is deliberately read off the disk rather than off ``git ls-files``,
    so it differs between a developer machine and a clean checkout. Two seeders
    matching ``seed_demo*.py`` are ignored by ``.gitignore`` and exist only
    locally: 74 files here, 72 in CI, measured 2026-08-03. That asymmetry is the
    point. Those two files reach neither pre-commit nor CI by any other route,
    and a name that lands in them is a name a developer can still put on screen
    when seeding a demo estate by hand.
    """
    found = sorted(
        {
            *(_APP / "scripts").glob("seed_demo*.py"),
            *(_APP / "scripts").glob("seed_flagship*.py"),
            *(_APP / "core" / "demo_packs").glob("*.py"),
            *(_APP / "core").glob("demo_projects.py"),
            *_APP.glob("modules/*/seed.py"),
        }
    )
    assert found, f"no demo seed sources under {_APP} - the globs have gone stale"
    return found


def _placeholder_lines() -> list[tuple[str, int, str]]:
    """Locale example values, which are demo data users read on screen too.

    Only lines carrying a ``_placeholder`` key are returned, never whole locale
    files. That is what keeps this surface usable: a locale file is tens of
    thousands of lines of translated prose, and scanning it whole would make
    every ordinary word in twenty nine languages a false positive waiting to
    happen. A placeholder value is a handful of words showing the user what to
    type, so it is the same shape as a bidder row.

    Returns an empty list when the frontend is absent, so a backend-only
    checkout still runs. The companion glob test below is what notices if this
    goes empty on a checkout that does have a frontend.
    """
    locales = _BACKEND.parent / "frontend" / "src" / "app" / "locales"
    if not locales.is_dir():
        return []
    rows: list[tuple[str, int, str]] = []
    for path in sorted(locales.glob("*.ts")):
        rel = path.relative_to(_BACKEND.parent).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "_placeholder" in line:
                rows.append((rel, number, line))
    return rows


def _scriptio_continua_runs(lowered: str) -> list[str]:
    """Maximal runs of a script that does not separate words with spaces."""
    runs: list[str] = []
    current: list[str] = []
    for char in lowered:
        if _is_scriptio_continua(char):
            current.append(char)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def _masked(text: str) -> str:
    """First and last character plus length, so a failure locates without reprinting."""
    return f"{text[0]}{'*' * (len(text) - 2)}{text[-1]} (len {len(text)})"


def test_the_seed_source_globs_still_reach_the_files_that_leaked() -> None:
    """A rename or a move would make every other assertion here vacuous."""
    names = {p.name for p in _seed_sources()}
    for expected in ("seed_demo_4d5d.py", "seed_demo_estimates.py", "demo_projects.py"):
        assert expected in names, f"{expected} is no longer in the scanned set"
    # Deliberately far below both real counts, because the count is machine
    # dependent by design, see _seed_sources. This guards against a glob that
    # stops matching, not against the two file difference between CI and a
    # developer checkout.
    assert len(_seed_sources()) > 40, "the scanned set shrank unexpectedly"


def test_the_locale_placeholder_surface_is_not_empty() -> None:
    """A key rename would leave the placeholder test green over nothing.

    ``_placeholder_lines`` returns an empty list on a backend-only checkout by
    design, and an assertion over nothing passes. Skip rather than fail in that
    case, so the distinction between "no frontend here" and "the key naming
    convention moved" stays visible instead of collapsing into one green tick.
    """
    locales = _BACKEND.parent / "frontend" / "src" / "app" / "locales"
    if not locales.is_dir():
        pytest.skip("no frontend in this checkout")
    rows = _placeholder_lines()
    assert rows, "no _placeholder keys found - the naming convention has moved"
    files = {rel for rel, _, _ in rows}
    assert len(files) > 20, f"only {len(files)} locale files carry placeholders"
    # The key that leaked. Named explicitly so its removal is loud rather than
    # a silent shrink in a count that is large enough to hide it.
    assert any("tendering.company_placeholder" in line for _, _, line in rows), (
        "tendering.company_placeholder is no longer in the scanned lines"
    )


def _scan(rel: str, number: int, line: str) -> list[str]:
    """Apply all three rules to one line. Returns located, masked failures."""
    hits: list[str] = []
    lowered = line.lower()
    for token in _TOKEN_RE.findall(lowered):
        if _MIN_LEN <= len(token) <= _MAX_LEN:
            if hashlib.sha256(token.encode()).hexdigest() in _DENY_TOKENS:
                hits.append(f"{rel}:{number}: firm token {_masked(token)}")
    # Two ordinary words in sequence, which no token rule can express.
    words = _WORD_RE.findall(lowered)
    for first, second in zip(words, words[1:], strict=False):
        phrase = f"{first} {second}"
        if hashlib.sha256(phrase.encode()).hexdigest() in _DENY_PHRASES:
            hits.append(f"{rel}:{number}: firm phrase {_masked(phrase)}")
    # Names no ASCII rule can express. Containment inside each run of a script
    # that does not space its words, which keeps this to a few windows per line
    # instead of one per character position.
    for run in _scriptio_continua_runs(lowered):
        for length in _SUBSTRING_LENGTHS:
            for start in range(len(run) - length + 1):
                candidate = run[start : start + length]
                if (length, hashlib.sha256(candidate.encode()).hexdigest()) in _DENY_SUBSTRINGS:
                    hits.append(f"{rel}:{number}: firm name {_masked(candidate)}")
    return hits


def test_no_demo_seed_source_names_a_real_firm() -> None:
    hits: list[str] = []
    for path in _seed_sources():
        rel = path.relative_to(_BACKEND).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hits.extend(_scan(rel, number, line))

    assert not hits, "demo data names real companies:\n" + "\n".join(hits)


def test_no_locale_placeholder_names_a_real_firm() -> None:
    """The example values users read in an empty form field.

    Separate from the seed test above because the two fail for different
    reasons and a reader needs to know which surface leaked.
    """
    hits: list[str] = []
    for rel, number, line in _placeholder_lines():
        hits.extend(_scan(rel, number, line))

    assert not hits, "locale example values name real companies:\n" + "\n".join(hits)
