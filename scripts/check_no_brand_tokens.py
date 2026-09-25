#!/usr/bin/env python3
"""Fail the build if a competitor brand leaks in, or a named CAD tool loses its mark.

Two rules live here and they are not the same rule.

Competitor products must never appear in any commit, code, UI string, changelog
or build artifact. Internal research stays internal; everything shippable uses
neutral generic names. The hashed denylist below enforces that one.

CAD authoring tools we convert FROM are the documented exception. Naming them is
the only way to tell a user which files the pipeline actually reads, so they are
allowed in UI strings, and the founder ruling of 2026-08-14 settles the form:
the first mention in each string carries the registered sign, which is the same
treatment the marketing site has used since 2026-07. The trademark form check
enforces that one. It is deliberately hash-free, because here the word is
permitted and only its form is in question, so the report can name it outright
instead of masking it.

English reaches a user through three surfaces, and a check that guards one of
them reports green over the other two. A locale value is the surface everyone
thinks of; an i18n default inside a component is the fallback when a key is
missing, and `guide.eac.selectors.body` has no entry in any of the forty
locales, so its default is the only English that will ever render; a bare
quoted literal in a component never went through i18n at all. All three are
scanned. What is deliberately NOT marked is data: a file-format token
(RVT/DWG/IFC/DGN), a code identifier, the converter's repository slug, a
shipped release note, and a rule pack's `name`, which another file matches
against byte-for-byte.

This gate enforces both automatically so neither relies on a reviewer
remembering. It is wired into both the local pre-commit hook and CI, exactly
like ``check_version_sync.py``.

Brand-safe by design: this file stores only SHA-256 hashes of the lowercased
brand tokens, never the literal brand strings, so the denylist itself does not
put a brand name in the repo. Because SHA-256 collisions are infeasible, the gate
matches ONLY the exact brand tokens, which means it cannot raise a false positive
on an unrelated word. Generic dictionary words that happen to also be product
names are intentionally left out of the automated list (they would match the
ordinary English word) and are covered by human review instead.

When a match is found the report prints the file, line, and a MASKED form of the
token (first and last character plus length) so a developer can locate and remove
it without the log reproducing the full brand string.

Exit codes:
    0  no brand token found, and every named CAD tool carries its mark
    1  a brand token leaked, or a UI string dropped the mark (file:line listed)

Usage::

    python scripts/check_no_brand_tokens.py                # scan all tracked text files (full audit)
    python scripts/check_no_brand_tokens.py path/a path/b  # scan given files (pre-commit)
    python scripts/check_no_brand_tokens.py --since origin/main   # scan only files changed vs a ref (CI guard)

The ``--since`` mode guards against NEW leaks without failing on pre-existing
debt, which is the right way to turn the gate on while a one-time legacy cleanup
proceeds separately. Run with no args for the full audit that drives that cleanup.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# SHA-256 of the lowercased brand tokens. No literal brand strings in this file.
# Add a hash here (python -c "import hashlib;print(hashlib.sha256(b'<token>').hexdigest())")
# to extend coverage. Keep to unambiguous coined brand tokens to avoid matching
# ordinary words.
#
# Founder ruling (2026-07): third-party product names are purged from every
# shippable surface and referred to only by open format (DWG/RVT/IFC/DGN) or a
# neutral category. CAD/BIM coordination product names are therefore denylisted
# below as well. The few genuinely load-bearing uses (our own DDC converter
# repository URL, a file-format detection value the parser compares against) are
# kept precise via the allowlist plus human review, so enforcement never breaks
# our own integration code.
#
# Amended 2026-08-14: the authoring tool the converter reads from is named in UI
# strings rather than purged, so it is deliberately absent from this list. It is
# not an oversight and must not be hashed in: the trademark form check below is
# what governs it, and hashing it would forbid the very strings that ruling
# permits.
_DENY_HASHES: frozenset[str] = frozenset(
    {
        "a62ee5ab3e8914010c0f75ff149f9415c839c64ccf4d8ed91d13b456dbc1d813",
        "d5b51a471ae081ca48018c369ce9341a4db134246a8a7c56dd47df5103e0c8a7",
        "46621e84f68449c6e68788cb4d78d8118cf2511999dc3136f9542ddf21fc2861",
        "fff045f2575092eee58374e6b24e2c3efae8533ac17811cf15939d4fd09a5284",
        "55af965522a877fbb91c42cc317bc592e7ac2282c8b986ea24d9d19b87f3e6de",
        "175144ba7727300741c47f7c881c12c1da553776a583e10c620cd4d24dc2d1ed",
        "6a3007f60515e405e5f64b07885dd24b25262525761bd45808afed3f82425b8e",
        "bf6c262b9b067db8fdc18a6cb0e78d1244553b65c4e9e48d3546af68e0a437a9",
        "423d16ce8c066ceb5714dbb2f9d16eaa59e3571d0318367039755e7e64ceb32f",
        "46c955d11d47c3d563abeefd1eca2b7c9546169b20d2f24cbb897f2fd4ed9ef8",
        "c04ecdbcc01c4eb5a7f93222146d5f4ed5f280a2ed134f7c7c9d4a52c268b6f0",
        "7d451b6eb01abdb0edf3c7fc440f6d06b3aa93223bca35dc207c31aa07da7121",
        "66d4c34f63b321e5d488acb27ceeff03e58861dc822786ecc16228ab966e560a",
        "9c13fc96144b74b5f10957d73a193662ca94dccb1148041280a9f673267150da",
        "f271bb49840f247f06d44e248a58da4f07a15ac13d19c908f3562cf4c27758ea",
        "a5c4fcc701283c5ed540c2963ba42e1f7af1ef3fed2e491525ef0c3a06d3272b",
        "5b02e0eece69d3f4ad8c913705c45d562b1fdd9672d294bb7ebd7aae75f68bad",
        "01fdc206bcfcd06718f3b964c4d6925905d879cee45d7611d4d3e4f414625239",
        "33df103969d7c653bc10754a41a8dc2156aabd7c33647241926d465ba721bb97",
        "f87e86b8abde90aa4ce0d2547c4465280baad22e833afadbebac3d670ea43617",
        "31135ce02873713edfb32a09bf723e1f436fdb080a8457189147a3f34a9412aa",
        "469be0d71cacd255ba602021b352bdba3c4c736eb3dafb824b48fc8c80971209",
        "21ab87a7ea9a7f6f2c7894beb361a8644f8fed69cad090265583d2edceb4966d",
        "9a2e8e955be161ed90ccef3ab2ce3a6a1e439de4a12b8af75536fd0f2ca1b66f",
        "78f01fedb12362675c783eb39ac7afa7c63a9c8d6d56e0542f1565cf026a8612",
        "7bc4be30839398ae59b2f9b2b8144671794537ad9bd829c9e73a93fbd9e51821",
        "fb6061067f2f48fe42db037321556e2c2ecee66c56b75ce935523d51bae05565",
        "48a712c1a4da10ef9c77d217372b97e875800f6a80e4f5bec36ed1b0fe3e921b",
        "2779934ff606047d5b140b82939b66fc88c9ba101a05d156086d71c1285d4bfb",
        "0b955e689bea821d4646d62739a8dec68ee9baf50c4b1e9f7e6fe8e23c75fc03",
        "1cf0fde0df3ac7d0d4af1ad80ebd7bdcdb5c27eb2518594d55a3f59773cc3f3f",
        "a2f98c7785a1629a12cc425bef2583336aef29d12b6c18fcee64f1469454289d",
        "3ccbd9105a45d8fcd4a0101c6532c599f6f59cfa4d4ce378792f547a869a4bea",
        "404e91050d105f97f8785b94706814e4a6ead40fea25c0ecf9efefa6bea999f5",
        "58b4537b616e657203a685e86b79ab85c981615d4c0ad243608f457cbbe0de34",
        "8ae56be495a96f1f31eabe97921415525913c2985c70b473631f52dee05c25be",
        "e0a27b93a6c5fd64c53a87e60bf2eff7113e271567044c910576f2c5dd760e0f",
        # 2026-08-31: a commercial cost-database product named in the Canadian
        # pack's description and README, on both of which it shipped. The gate
        # did not hold it, so the purge was one file edit away from coming back
        # the next time somebody described the pack from memory.
        "535951eee5c78021bdca282e8c240c4df6c4fcab24a44b86e26799b64b6c9784",
        # 2026-07 purge: pure competitor tool names (BCF coordination, BIM
        # authoring, estimating, construction management). Format-intrinsic vendor
        # names that spell a file format's own vocabulary (the DWG version labels
        # and binary sentinel, the RVT/DGN header strings) are NOT hashed here -
        # they are functional-interop, kept off the gate and genericized only on
        # user-facing surfaces by review, per the note above.
        "5f37acd72c2cc038391bde05c11697a168667aa4a27c886638faecfd25b1bdd6",
        "aec4c46090689ecbff828e189c03de452bf3709710b168b0864079e631f772d5",
        "5db318368f0b9f5974d745815cfb9290560966eb7c0fac6077192761748bf07e",
        "82713ff6e800821047c46a2c29642fdaee6f4a3dcf2d98006edac2b311340926",
        "7175b0331bdaf8b428d33897b5b55983293776a5a9ca9ea8612cce412003b442",
        "bac8736b4055203b1e2fbbf131280979d0342920a5d1646e257a9a9e6727fcbd",
        "804a7ac7d37b4944a2c02f8e3f6826aa6c15ec82d8ae848f62cac5d0be9e7af3",
        "55efa080d02d76fdd9021db48718aeababaafa85f082ab4152db505b26f6cbf8",
        "62cfc917c13eda7b31202f66f8378344d69f601bab9c89e043807dc763f1e0bc",
        "96aed7c729899185bf13863acea99b958f81be3d5222ea709d49aa0af3e7446b",
        "5696c9f4a0e58aa85c12d312e051162363c3f29a1fcdf0da152f43bf9a7a604b",
        "0aab8b5450e4846d17896c6115b1620d6b5b6ad130666845845c02554546c746",
        "5971b0dc06256600737ca8ba133808b5d8122016a777948e998535036594a95b",
        # 2026-08: real contractors and design practices that reached users as
        # demo tender bidders and project metadata. They were named in
        # app/scripts/seed_demo_4d5d.py and seed_demo_estimates.py, which the
        # earlier demo sweep did not reach, and shipped in every wheel up to
        # 14.2.1. Surnames are hashed one token at a time because the scanner
        # sees maximal [a-z0-9]+ runs, never a two-word company name.
        "b4d969421ab34a7895fc58810b7f1ffc93520b10c9cc6c403ca607b9f29f8c04",
        "f38f6d7164bf334b3282eda983dcb8d5b69e2e14ffa7b4a83532d61aa7ee03be",
        "65266ec0e12375d08a468a83da9d63a57eaaa9a24c3e5cd055ad706598310752",
        "e3c7e82d53a1ce84c284f43915a66bf147c75b2a8baf3f2d476bd2ecd754590c",
        "4e44ac61bc0519ecccc8ae9c2dae453f13ca786a647087c7a2266a6ec5232c94",
        "09c7945dc8a40843b498d79e60716cf57772480d518db5afbbd2d6ab880826fa",
        "20920c3de23ff769ee1c1113c409113c10f7c9d752b55660c3e6b8137589e66a",
        "5fda8083a1784f7ebb246f2d52001eaaf75e1ce06437f297e12b5e5843659f81",
        "fda1bdcc3e8d94633b84d1ec2277cb3400d298a431259af0d46479732d98c15d",
        "ad05969625c093458a9e1df667770ccf71a19b58159126854bd4bda44f0fdaba",
        # Coined replacements that turned out to collide with live construction
        # firms and were withdrawn before release. Hashed so they cannot be
        # invented a second time: the collision rate on plausible-sounding names
        # is roughly one in two, and a name that reads clean is not evidence.
        "467813f7cf203871621e08b72ee4c210215b1f6a4af0e27da53a3cb490fe8bdf",
        "e186dc4cc7fad46dc412de303e24ee681bfe746267c6488d4af0267122f9f6d7",
        # Two more of the same kind, both found in shipped demo data rather than
        # in a candidate list. One was rejected during an earlier sweep for a
        # reason recorded at the time and shipped anyway, which is why rejection
        # has to be written down as a hash and not as a note.
        "f560bc02f626b8160149369482ae0a5827ba6c8bf1da3a53e1a0426afb0a4e02",
        "3baeea126007538168b11698b963e28e40635c3708ae610b17c382bac9dce1fa",
        # Added 2026-08-23. Until now this list held CAD and BIM authoring
        # products only, so it was a gate on the software category and nothing
        # else, and it reported clean over the whole tree while eight rows of a
        # shipped catalogue carried formwork manufacturers' registered system
        # names. It had never been asked the question, so its silence meant
        # nothing.
        #
        # The category added here is formwork, falsework and scaffolding
        # equipment: manufacturers and the coined names of their panel, table
        # and climbing systems. That category is picked because it is the one
        # that demonstrably reaches our data. Equipment vendor names arrive
        # through the formwork catalogue, through seeded demo data, through
        # partner packs and through design notes, and every one of those routes
        # already had a name on it when this was written.
        #
        # It stops there on purpose. Plant hire and material manufacturers can
        # reach the same surfaces, but the set is unbounded and mostly ordinary
        # words, and a hash added on the strength of "it matches nothing today"
        # is unauditable: nobody reading this file can tell what it forbids, so
        # nobody can tell whether a future false positive is a bug or the rule
        # working. Every entry below was measured against the tracked tree
        # first, and the ones that convicted ordinary text were dropped rather
        # than shipped and argued about later.
        "22ce25d79c242941f812633f0e66abda64ae5c0b0a678bc05025bfb0dc77b040",
        "407c149d9c9e20a40ea74548b08dbdd51d68a2daabda73c380683d0c6b1fea8d",
        "c216f885fdedc93115d30ff7b3e5d04237c0c30649833fe091529742b7d2f376",
        "7e06673882b200d3b6100a75e37dedbde5c0f25ed53d2c519d7d1028d0ae2ae5",
        "75acd79ffb903cdb03760c6d0451f1252904f58a35b3c87fb364ed0cffb8815b",
        "6efb021c3927e33f662cdf6ee15e03e43eea4e6e5051b8853eeeecefe758e573",
        "aeb34d960ccb124c33f726f6c509853fb46b0a9cf1f0c9c48472378e30ef4997",
        "52b38652058e5ca583119ce6492939a049ba49700ad6e8cb28138eb28f00b2e4",
        "949cf01c2c5166b277dbe6d11fd2b70bcc30ea9fd55007bb0d89349e5ca95026",
        "69f36671eddaa41964291019fe62b01743ba6da8c89c1267f08a8124bf5a55f2",
        # System names from the same category that arrived through a partner
        # pack rather than through the catalogue. They are listed separately
        # because they have no replacement recorded in _REPLACEMENT_OF below:
        # nothing in the product renames them, so no file can ever be excused
        # for carrying one.
        "ec4188114ad20f506af05aea2ea67489c954672b82be22b256115ce744c2f718",
        "3e86e0d516fafa37db2207120cbdde8d221a292c125f7cc1ab4b55490ca75bb1",
        "3bc87656ead9ecede45114b0463fbd44dbba1eb7ab717af447db4763a70b8b71",
        "7e11a130e9befa6c0d8c5655449d4ccd035d193053e84f6a5b89b7f68bb2e401",
        "8bcd3837a4469ff20ab81a94a4438c2e2032bdecb992a36281f05cf3ebd1f7cc",
        "96a5c2da7115315c06913af37b8bd3078b25fe97587b1b903e7734ded302c52e",
        "a115cb46aa305477439815f9855d5040f3d1d3472becefe6327b817e0f3fe731",
        "19bcf2b8faab323b5e90f9f9e388cf53b9387df89793970a28f44974e03beeb9",
        # Four manufacturers in this category are deliberately NOT hashed, and
        # this is the record so the work is not repeated. Two four-letter ones
        # collide with real text: one is a Slavic verb stem that appears across
        # the Czech and Croatian locales once the tokenizer splits a word on its
        # non-ASCII letter, the other is both a perimeter abbreviation in our
        # own raster code and a Spanish and Finnish word stem. A six-letter one
        # is ordinary unaccented Portuguese and appears throughout pt and pt-BR.
        # A fourth is a three-letter acronym that is already a legitimate
        # commissioning term here and is below _MIN_LEN in any case. Their
        # products are still covered where the product name itself is coined;
        # one system, whose only distinctive word is that acronym, cannot be
        # caught by a token gate at all, and no bound exists that would catch it
        # without convicting ordinary text.
    }
)

# Brand tokens are coined names 4 to 14 characters long. Only hash candidate
# runs in that range so the scan stays fast on large files.
#
# The lower bound was 5 until 2026-08-23, which put four-letter manufacturer
# names out of reach entirely. It moved down after the candidates were counted
# across every tracked text file: the two four-letter names added above match
# nothing outside the files that rename them, and the two that matched ordinary
# words were left out rather than the bound left alone. Lowering the bound
# cannot by itself convict anything, since a run is only ever compared against
# the list; only a careless entry can, which is why the entries were measured.
_MIN_LEN = 4
_MAX_LEN = 14
# Two patterns and a fold between them, because the single ASCII pattern this
# check used until 2026-08-24 was wrong in both directions at once. It ended a
# run at every character outside [a-z0-9], so any separator walked a denied
# name straight through, and every non-ASCII letter ended a run too.
#
# That second half was the expensive one, and it had already cost us three
# different ways. It cut accented words into fragments, which is how ordinary
# Croatian and Spanish prose came to collide with four-letter product names,
# and why two names in this field could not be listed at all. It made a name
# written with its own umlaut unreachable, so one entry below had been recorded
# as the fragment left over after the mark was dropped, and another was
# recorded whole and could therefore never match anything. And it reduced every
# non-Latin script to nothing at all, so a line of Han characters produced no
# run to compare and the check returned clean because it could not read the
# line, which is the one result a check must never give.
#
# So a run is now any sequence of letters or digits in any script, with the
# underscore excluded so that a snake_case identifier still separates into its
# parts, and each run is folded to its base letters before it is compared.
# Marks are stripped before the run is cut as well as after, because text that
# arrives decomposed carries them as separate characters that would otherwise
# end the run exactly as before, and some tracked files are stored that way.
# Compatibility forms fold too, which closes the trick of writing a name in
# full-width Latin.
#
# Text that is pure ASCII cannot carry a diacritic or a non-Latin letter, so it
# takes the original path unchanged, and because the unit here is a line rather
# than a file, nearly every line in the tree still takes it. Both versions were
# run alternately in one process over the whole tree to keep the file cache out
# of it: the full pass CI runs came out at 114s against 123s for the version
# this replaces. The extra work on the lines that do carry an accent is more
# than paid for by matching runs directly rather than through match objects.
_ASCII_RUN_RE = re.compile(r"[a-z0-9]+")
_RUN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_MARK_RE = re.compile(
    r"[̀-ͯ҃-҉֑-ֽً-ٟ"
    r"᪰-᫿᷀-᷿⃐-⃰︠-︯]"
)


def _tokens(text: str) -> list[str]:
    """Cut `text` into lowercased, mark-folded runs of letters and digits."""
    lowered = text.lower()
    if lowered.isascii():
        return _ASCII_RUN_RE.findall(lowered)
    runs = []
    for run in _RUN_RE.findall(_MARK_RE.sub("", lowered)):
        if not run.isascii():
            run = _MARK_RE.sub("", unicodedata.normalize("NFKD", run))
        if run:
            runs.append(run)
    return runs


# Taking a name out of the product requires writing it down somewhere. The code
# that renames the catalogue rows still carrying it needs the exact old strings
# as search keys, the frozen revision that renames the same rows holds them for
# the same reason, and the test that proves the rename happened has to seed them
# to have anything to rename. Those files are about the names. An ordinary file
# that mentions one is using it. A gate that only asks whether the name is
# present cannot tell those apart and convicts all of them.
#
# The obvious answer is a list of paths that are allowed to carry it, and that
# answer is how a gate dies: the list grows by one every time somebody is
# blocked, nobody re-reads the entries, and eventually it is the list that
# decides what ships rather than the rule. So the distinction here is drawn on a
# property of the file's own content instead.
#
# A file that renames something must say what it renames it to. A file that
# merely mentions the thing has no reason to. So a denied token is passed over
# only in a file that also contains the plain descriptor that that particular
# token is renamed to. It is per pairing, not per file: in the same file, a
# denied token whose replacement is absent is still reported on its own line.
# Nothing has to be maintained, nothing can be added by asking, and a file that
# stops doing the rename stops being excused the moment it does.
#
# Both sides are hashes, so this file still contains no brand literal and no
# catalogue string. Keys are the token hashes in _DENY_HASHES; values are the
# word count of the replacement phrase and the hash of that phrase, reduced the
# way _normalised_words reduces a file. The word count is stored because a hash
# cannot be searched for - the file's own text has to be cut into phrases of the
# right length and hashed to be compared.
_REPLACEMENT_OF: dict[str, tuple[int, str]] = {
    "22ce25d79c242941f812633f0e66abda64ae5c0b0a678bc05025bfb0dc77b040": (
        4,
        "f6114669fcf7090eb2a058763b8cd89d6e7b2836c59f9c8fde058e579fea386c",
    ),
    "407c149d9c9e20a40ea74548b08dbdd51d68a2daabda73c380683d0c6b1fea8d": (
        4,
        "f6114669fcf7090eb2a058763b8cd89d6e7b2836c59f9c8fde058e579fea386c",
    ),
    "c216f885fdedc93115d30ff7b3e5d04237c0c30649833fe091529742b7d2f376": (
        4,
        "eb65551a8a8acd13d9e2be9728779295ce5a6b597b3c0582d92c50866df3dad4",
    ),
    "7e06673882b200d3b6100a75e37dedbde5c0f25ed53d2c519d7d1028d0ae2ae5": (
        4,
        "25a1972db98d617db0775fdfcf152737e9a75b8ccbe91b7ca0a2bed0b9c5361e",
    ),
    "75acd79ffb903cdb03760c6d0451f1252904f58a35b3c87fb364ed0cffb8815b": (
        5,
        "6d256d58b7e6ab76199d81a6e43f7dbf7b6d2c309870cea62090c8fd71513d4d",
    ),
    "949cf01c2c5166b277dbe6d11fd2b70bcc30ea9fd55007bb0d89349e5ca95026": (
        5,
        "6d256d58b7e6ab76199d81a6e43f7dbf7b6d2c309870cea62090c8fd71513d4d",
    ),
    "6efb021c3927e33f662cdf6ee15e03e43eea4e6e5051b8853eeeecefe758e573": (
        5,
        "e1207df5d069b2a6cfd25d60594fdadae21fb92f65f4062d796dcef0b7c84012",
    ),
    "aeb34d960ccb124c33f726f6c509853fb46b0a9cf1f0c9c48472378e30ef4997": (
        5,
        "e1207df5d069b2a6cfd25d60594fdadae21fb92f65f4062d796dcef0b7c84012",
    ),
    "52b38652058e5ca583119ce6492939a049ba49700ad6e8cb28138eb28f00b2e4": (
        3,
        "432408f4505febd6864ab7ac9507957effe7b2cbe91defca228be3976ced8803",
    ),
    "69f36671eddaa41964291019fe62b01743ba6da8c89c1267f08a8124bf5a55f2": (
        3,
        "432408f4505febd6864ab7ac9507957effe7b2cbe91defca228be3976ced8803",
    ),
}


def _normalised_words(text: str) -> list[str]:
    """Reduce `text` the way both sides of a replacement pairing are reduced.

    Lowercase, mark-folded runs of letters and digits, nothing else, exactly
    as _tokens reduces a line. Punctuation and line breaks disappear, so a
    hyphenated descriptor matches its unhyphenated form and a descriptor
    wrapped across two source lines still matches. Both sides have to be
    reduced by the same function, or a pairing stops being recognised the
    moment either side carries an accent.
    """
    return _tokens(text)


def _replacements_of_length(words: list[str], size: int) -> set[str]:
    """Which `size`-word replacement phrases does `words` contain?

    One pass answers for every pairing of that length at once, rather than one
    pass per denied token. Written this way after the first full-tree run, where
    a 4.6 MB generated file held two denied tokens whose replacements are the
    same length and each of them walked the whole file end to end. The cost is
    now bounded by the number of distinct phrase lengths, which is three,
    instead of by the number of tokens a file happens to contain.

    Only ever reached for a file that already holds a denied token, so an
    ordinary file pays nothing for this at all.
    """
    targets = {digest for length, digest in _REPLACEMENT_OF.values() if length == size}
    found: set[str] = set()
    for start in range(len(words) - size + 1):
        phrase = " ".join(words[start : start + size])
        digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()
        if digest in targets:
            found.add(digest)
    return found


# Only scan source and content file types; skip binaries and vendored trees.
_TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".md",
    ".mdx",
    ".html",
    ".css",
    ".scss",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".sql",
    ".sh",
    ".env",
    ".cfg",
    ".ini",
    ".rs",
    ".vue",
    ".svelte",
    # An SVG is markup, not a picture, and a logo traced into one carries the
    # name in its title, its id and its class attributes. Leaving the suffix out
    # meant the gate listed all 94 tracked SVGs and then dropped every one of
    # them on the way in. Measured at zero hits across those 94 before adding
    # it, so this closes a hole rather than declaring an amnesty.
    ".svg",
}
_SKIP_PARTS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
    "target",
    "_frontend_dist",
}
# This gate stores hashes, never literals, so it never matches itself, but skip
# it anyway to keep the report clean.
_SELF = Path(__file__).resolve()

# Embedded static mirror of DataDrivenConstruction's own converter website
# (datadrivenconstruction.io), kept as a marketing asset. It is not the product
# UI; its cad2data pages name the CAD formats that converter reads and write, plus
# real external blog URLs, which is functional for that product rather than a
# competitor-brand leak in ours. Excluded so the gate does not fight that asset.
_SKIP_FILES = {
    (REPO_ROOT / "website-marketing/pro/breeze/assets/people/ddc_home.html").resolve(),
}

# Reviewed functional-interop exceptions (e.g. an import-format name or an
# integration-target list that tells a user what they can actually connect to).
# Each line is `<path-substr>||<line-substr>`: a hit is allowed only when the
# file path contains <path-substr> (empty = any file) AND the matched line
# contains <line-substr>. This stays precise - a new brand on a different line
# is still caught, because it will not carry the reviewed context substring.
_ALLOWLIST_FILE = REPO_ROOT / "scripts" / "brand_token_allowlist.txt"


# Named CAD authoring tools: allowed in UI strings, required to carry the mark.
# Literals, not hashes, because the point is the form of a permitted word.
_MARKED_NAMES = ("Revit",)
_REGISTERED = "®"
_LOCALE_DIR = "frontend/src/app/locales/"

# A locale entry is one line, `"some.key": "the display string",`. Only the value
# is display text: a key such as `bim.filter_revit_categories` is an identifier
# and is never marked, so the check reads group 2 and ignores group 1.
_LOCALE_ENTRY_RE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:\s*"(.*)"\s*,?\s*$')

# The one context where the name is an identifier rather than a display name:
# the converter's own repository slug, which is part of a URL and must stay
# byte-exact. Anything else that looks slug-like is still reported, because a
# gate that guesses at new slugs would rather quietly permit than ask.
_SLUG_PREFIX = "cad2data-"

# English that ships inside a component instead of a locale file: an i18n
# default. Locale files are not the whole UI, and `guide.eac.selectors.body`
# proves it - that string has no entry in any of the forty locales, so its
# default is the only English a user will ever see and no locale gate can
# reach it. The hint may sit on the line above, because a long default is
# conventionally written as `bodyDefault:` and then the string.
_DEFAULT_HINT_RE = re.compile(r"default|fallback", re.IGNORECASE)
_FRONTEND_SRC = "frontend/src/"
_COMMENT_STARTS = ("//", "*", "/*")

# The third place English ships: a literal written straight into a component,
# with no i18n call and no locale entry behind it, so no translator ever sees
# it. A radio label, a format list and a thrown message all reached users this
# way. Single and double quotes only; see _scan_display_literals for why a
# template literal is not one of them.
_QUOTED_RE = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")
_FIELD_RE = re.compile(r"^\s*(\w+)\s*:")

# A test fixture is not a display string. `__tests__` alone misses the sibling
# convention (`BIMConverterVerifyGate.test.tsx`), which is how an unmarked
# fixture sat inside the scanned set while the gate read green.
_TEST_MARKERS = ("__tests__", ".test.", ".spec.")

# Ruled 2026-08-14: a shipped release note records what was written that day.
# It is a record, not a surface the product restyles, so the marks stay out of
# it. Marking it once and reverting is what settled this; do not re-mark it.
_ARCHIVE_FILES = ("frontend/src/features/about/Changelog.tsx",)

# Closed decision 2026-08-14 - do not reopen this by "fixing" the gate. A rule
# pack's `name` is its identity rather than a label: the same string is the
# pack name in data/bim_rules/*.yaml, and the copy seeded from the frontend has
# to stay byte-exact against it, so a sign on one side would rename the pack on
# that side only. `description`, sitting directly beside it in the same object,
# IS display text and does carry the mark. Scoped to the one file that holds
# seeded pack identities so it cannot quietly widen into an excuse elsewhere.
_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "frontend/src/features/bim_requirements/SEED_PACKS.ts": ("name",),
}


def _unmarked_first_mention(text: str) -> str | None:
    """Name the CAD tool whose first display mention in `text` lacks the mark.

    Only the first mention needs it. "Revit templates read Revit parameters" is
    correct usage, and demanding a sign on every repetition would make the gate
    reject the very wording the ruling produced. German and Nordic compounds
    keep the sign on the name itself, before the hyphen, as in Revit(R)-Modelle,
    so nothing about a following hyphen makes an occurrence exempt.
    """
    for name in _MARKED_NAMES:
        if name not in text:
            continue  # the common case, and far cheaper than a regex scan
        for match in re.finditer(re.escape(name), text):
            start, end = match.span()
            if text[:start].endswith(_SLUG_PREFIX):
                continue  # repository slug inside a URL, not a display name
            if text[end : end + len(_REGISTERED)] != _REGISTERED:
                return name
            break  # first display mention decides; later ones stay bare
    return None


def _code_before_comment(line: str) -> str:
    """Drop a trailing `//` comment, leaving a `https://` URL intact."""
    at = 0
    while True:
        at = line.find("//", at)
        if at == -1:
            return line
        if at and line[at - 1] == ":":
            at += 2
            continue
        return line[:at]


def _read_text(path: Path) -> str | None:
    """The file as text, or None when it is binary or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _scan_trademark_form(path: Path, text: str | None = None) -> list[tuple[int, str, str]]:
    """Report a locale string whose first CAD tool mention is missing the mark."""
    hits: list[tuple[int, str, str]] = []
    if text is None:
        text = _read_text(path)
    if text is None:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        entry = _LOCALE_ENTRY_RE.match(line)
        if not entry:
            continue
        key, value = entry.group(1), entry.group(2)
        name = _unmarked_first_mention(value)
        if name:
            hits.append((lineno, key, name))
    return hits


def _scan_component_defaults(path: Path, text: str | None = None) -> list[tuple[int, str]]:
    """Report an i18n default in a component whose CAD tool mention is bare.

    Same rule as the locale scan, applied to the other place English lives. The
    filter is the shape of the line rather than the file, so an identifier such
    as RevitCategory and a comment about the converter stay out of it: a gate
    that shouted at code would be turned off within a week.
    """
    hits: list[tuple[int, str]] = []
    if text is None:
        text = _read_text(path)
    if text is None:
        return hits
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith(_COMMENT_STARTS):
            continue
        previous = lines[lineno - 2] if lineno > 1 else ""
        if not (_DEFAULT_HINT_RE.search(line) or _DEFAULT_HINT_RE.search(previous)):
            continue
        name = _unmarked_first_mention(_code_before_comment(line))
        if name:
            hits.append((lineno, name))
    return hits


def _is_test_path(norm: str) -> bool:
    return any(marker in norm for marker in _TEST_MARKERS)


def _scan_display_literals(path: Path, norm: str, text: str | None = None) -> list[tuple[int, str]]:
    """Report a quoted display string whose CAD tool mention is bare.

    Scope is narrow on purpose, because a rule over every quoted string in the
    frontend reports text that must NOT be marked:

    Template literals are skipped. SEED_PACKS.ts embeds whole YAML rule-pack
    documents in backticks, and the first mention inside one lands in a ``#``
    comment of that embedded document - a comment this rule has no way to read
    as one. Those documents are the same bytes as data/bim_rules/*.yaml and are
    marked there instead, so nothing is lost by not reading them twice.

    Identity fields are skipped per _IDENTITY_FIELDS: a value that another file
    matches against is data, and marking it would edit the data.
    """
    hits: list[tuple[int, str]] = []
    if text is None:
        text = _read_text(path)
    if text is None:
        return hits
    lines = text.splitlines()
    identity = _IDENTITY_FIELDS.get(norm, ())
    in_template = False
    for lineno, line in enumerate(lines, start=1):
        was_inside = in_template
        if (line.count("`") - line.count("\\`")) % 2:
            in_template = not in_template
        if was_inside:
            continue
        if line.lstrip().startswith(_COMMENT_STARTS):
            continue
        code = _code_before_comment(line)
        field = _FIELD_RE.match(line) or (_FIELD_RE.match(lines[lineno - 2]) if lineno > 1 else None)
        if field and field.group(1) in identity:
            continue
        for match in _QUOTED_RE.finditer(code):
            body = match.group(1) if match.group(1) is not None else match.group(2)
            name = _unmarked_first_mention(body)
            if name:
                hits.append((lineno, name))
                break
    return hits


def _load_allowlist() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if not _ALLOWLIST_FILE.is_file():
        return entries
    for raw in _ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "||" not in line:
            continue
        path_sub, _, line_sub = line.partition("||")
        entries.append((path_sub.strip(), line_sub.strip()))
    return entries


def _is_allowed(relpath: str, line: str, allowlist: list[tuple[str, str]]) -> bool:
    rp = relpath.replace("\\", "/")
    return any((not path_sub or path_sub in rp) and line_sub and line_sub in line for path_sub, line_sub in allowlist)


def _git_files(args: list[str]) -> list[Path]:
    out = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = REPO_ROOT / rel
        if p.suffix.lower() in _TEXT_SUFFIXES:
            files.append(p)
    return files


def _tracked_text_files() -> list[Path]:
    return _git_files(["ls-files"])


def _changed_text_files(ref: str) -> list[Path]:
    # Files changed vs the ref (committed diff) plus anything staged/unstaged,
    # so the CI guard catches a leak whether it is committed or in flight.
    seen: dict[str, Path] = {}
    for spec in (
        ["diff", "--name-only", f"{ref}...HEAD"],
        ["diff", "--name-only", "HEAD"],
    ):
        try:
            for p in _git_files(spec):
                seen[str(p)] = p
        except subprocess.CalledProcessError:
            pass
    return list(seen.values())


def _mask(token: str) -> str:
    if len(token) <= 2:
        return "*" * len(token)
    return f"{token[0]}{'*' * (len(token) - 2)}{token[-1]} (len {len(token)})"


# Token -> its SHA-256. The same few words recur on almost every line of the
# tree, and hashing each occurrence afresh was the largest share of the audit's
# CPU time. Only the hash is remembered, never the verdict: membership is asked
# of _DENY_HASHES on every call, so a list that changes (a test swaps it) is
# never answered from a cache built against the old one.
_DIGEST_CACHE: dict[str, str] = {}


def _denied_digest(token: str) -> str | None:
    """The denied digest of `token`, or None when the token is not denied."""
    if not (_MIN_LEN <= len(token) <= _MAX_LEN):
        return None
    digest = _DIGEST_CACHE.get(token)
    if digest is None:
        digest = _DIGEST_CACHE[token] = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest if digest in _DENY_HASHES else None


def _file_may_hold_denied(text: str) -> bool:
    """Could any line of `text` yield a denied token?

    A pre-filter, so it must never answer no for a file the line scan would
    report. It cuts the whole file with the path _tokens takes for a non-ASCII
    line. On ASCII that path cuts exactly as the ASCII one does, marks never
    join across a line break because every line break is a non-word character,
    and lowercasing looks at no context wider than a word, so the runs found
    here are the union of the runs every line produces.
    """
    lowered = text.lower()
    if lowered.isascii():
        runs = set(_ASCII_RUN_RE.findall(lowered))
    else:
        runs = set()
        for run in set(_RUN_RE.findall(_MARK_RE.sub("", lowered))):
            if not run.isascii():
                run = _MARK_RE.sub("", unicodedata.normalize("NFKD", run))
            runs.add(run)
    return any(_denied_digest(run) is not None for run in runs)


def _scan_file(path: Path, text: str | None = None) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    if text is None:
        text = _read_text(path)
    if text is None:
        return hits  # binary or unreadable - nothing to check
    if not _file_may_hold_denied(text):
        return hits
    words: list[str] | None = None  # built on the first denied token, not before
    stated: dict[int, set[str]] = {}  # phrase length -> replacements this file states
    for lineno, line in enumerate(text.splitlines(), start=1):
        for token in _tokens(line):
            digest = _denied_digest(token)
            if digest is None:
                continue
            replacement = _REPLACEMENT_OF.get(digest)
            if replacement is not None:
                size, phrase = replacement
                if size not in stated:
                    if words is None:
                        words = _normalised_words(text)
                    stated[size] = _replacements_of_length(words, size)
                if phrase in stated[size]:
                    continue  # this file renames the name rather than using it
            hits.append((lineno, _mask(token), line))
    return hits


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--since":
        if len(argv) < 2:
            print("[FAIL] --since needs a git ref, e.g. --since origin/main")
            return 1
        candidates = _changed_text_files(argv[1])
    elif argv:
        candidates = [Path(a).resolve() for a in argv]
    else:
        candidates = _tracked_text_files()

    allowlist = _load_allowlist()
    failures: list[str] = []
    unmarked: list[str] = []
    allowed = 0
    for path in candidates:
        rp = path.resolve()
        if rp == _SELF:
            continue
        if rp in _SKIP_FILES:
            continue
        if any(part in _SKIP_PARTS for part in rp.parts):
            continue
        if rp.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if not rp.is_file():
            continue
        try:
            shown = str(rp.relative_to(REPO_ROOT))
        except ValueError:
            shown = str(rp)
        # Read once for all four scans. Opening a file is the dominant cost on a
        # workstation whose scanner inspects every open, and the three form
        # scans used to reopen what the token scan had just read.
        text = _read_text(rp)
        if text is None:
            continue  # binary or unreadable - every scan below would pass it
        for lineno, masked, line in _scan_file(rp, text):
            if _is_allowed(shown, line, allowlist):
                allowed += 1
                continue
            failures.append(f"{shown}:{lineno}: brand token {masked}")

        norm = shown.replace("\\", "/")
        if norm.startswith(_LOCALE_DIR):
            for lineno, key, name in _scan_trademark_form(rp, text):
                unmarked.append(f"{shown}:{lineno}: {key} names {name} with no {_REGISTERED}")
        elif norm.startswith(_FRONTEND_SRC) and norm.endswith((".ts", ".tsx")) and not _is_test_path(norm):
            # A default is also a quoted literal, so report each line once and
            # let the more specific message win.
            seen: set[int] = set()
            for lineno, name in _scan_component_defaults(rp, text):
                seen.add(lineno)
                unmarked.append(f"{shown}:{lineno}: i18n default names {name} with no {_REGISTERED}")
            if norm not in _ARCHIVE_FILES:
                for lineno, name in _scan_display_literals(rp, norm, text):
                    if lineno in seen:
                        continue
                    unmarked.append(f"{shown}:{lineno}: display string names {name} with no {_REGISTERED}")

    if unmarked:
        print(
            f"[FAIL] {len(unmarked)} UI string(s) name a CAD tool without the "
            f"registered sign - add {_REGISTERED} to the first mention:"
        )
        for u in unmarked:
            print(f"  {u}")
        print(
            "\nThe name itself is allowed. Only the first mention in a string "
            "takes the sign; later mentions in the same string stay bare."
        )

    if failures:
        print("[FAIL] competitor/vendor brand token(s) found - remove and use a neutral name:")
        for f in failures:
            print(f"  {f}")
        print(
            "\nThese product names must never appear in the repo. Replace with the "
            "neutral generic term used elsewhere in the codebase."
        )

    if failures or unmarked:
        return 1

    note = f" ({allowed} reviewed interop exception(s) allowed)" if allowed else ""
    print(f"[OK] no brand tokens in {len(candidates)} scanned file(s){note}")
    print("[OK] every CAD tool named in a UI string carries the registered sign")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
