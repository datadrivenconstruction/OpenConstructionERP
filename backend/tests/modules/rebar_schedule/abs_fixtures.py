# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ABS records written here, from the format rules, for these tests.

These are ours. Nothing below is copied from anybody's document. Every record
was written from the rules stated in
:mod:`app.modules.rebar_schedule.abs_format` - the block grammar, the header
field order, the applicability table per super-group - and every number in it
follows from something a reader can check:

* Bar weights are the length in metres times the mass per metre of the
  diameter, taking steel at 7850 kg/m3: 0.888 kg/m at 12 mm, 0.617 at 10 mm,
  0.222 at 6 mm, 0.154 at 5 mm.
* Bending rollers are four times the bar diameter, which is the smallest
  roller DIN 488 allows below 20 mm: 48 mm for a 12 mm bar, 40 mm for a 10 mm
  bar.
* The developed length in a header is the sum of the geometry's legs, an arc
  contributing ``radius * angle`` in radians. That is what
  ``bvbs_abs.developed_length_matches_header`` checks, so the two agree here by
  construction rather than by luck.
* Grades, mesh types and the like are standard designations or plainly
  invented names. No product of any manufacturer is named.

The corpus proves itself. Every ABS record ends with a checksum over its own
characters, ``96 - (sum of the ASCII values through the C of the checksum
block) mod 32``, so a record can be shown correct on its own without any
outside copy to compare it against. :func:`_prove` runs that check over every
record at import, which means a typo in this file fails the whole module at
collection rather than one test somewhere downstream.

What the corpus deliberately gets wrong, and why
------------------------------------------------
Two entries carry a defect on purpose. Both existed to stop a later reader
loosening a rule to accommodate a record that does not conform, and both keep
that job without needing anyone's record to point at.

:data:`HEADER_INCOMPLETE` names the one record whose header omits fields its
super-group requires, the weight ``e`` and the author ``v``. It is here so the
whole-file tests have something to import that goes red, and so the header rule
can be held to the standard's text - every applicable identifier present, even
when the value is empty - with a test that pins which record is short and by
what. A rule relaxed to let this record through would be caught immediately.

:data:`BFGT_MISSTATED_CHECKSUM` is a lattice girder whose checksum block states
a value its own characters do not produce. The standard's checksum table does
not mark BFGT as carrying a checksum block, which invites a reader to exempt
the super-group from the check altogether; this record is here so that exemption
cannot be made quietly.
"""

from app.modules.rebar_schedule.abs_format import compute_checksum, verify_checksum

#: One well-formed record per shape the codec and the rules have to handle,
#: keyed by what the shape is. Every one reproduces its own checksum. Exactly
#: one, ``spacer-positions``, is reported by a validation rule - see
#: :data:`HEADER_INCOMPLETE`.
RECORDS: dict[str, str] = {
    # Two legs meeting at a right angle, 300 + 700 = the 1000 mm the header
    # states. The plainest record there is, and the one most tests reach for.
    "bar-with-one-bend": "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l700@w0@C93@",
    # 180 degree hooks at both ends: 150 + 500 + 150 = 800.
    "bar-with-hooked-ends": (
        "BF2D@HjOCE-DEMO@r312@ib@p2@l800@n10@e0.710@d12@gB500B@s48@v@Gl150@w180@l500@w180@l150@w0@C82@"
    ),
    # A cranked bar, the offset leg 354 mm because 250 mm at 45 degrees is
    # 250 * sqrt(2). Legs sum to 1154.
    "cranked-bar": (
        "BF2D@HjOCE-DEMO@r312@ib@p3@l1154@n10@e1.025@d12@gB500B@s48@v@"
        "Gl150@w90@l250@w45@l354@w-45@l250@w-90@l150@w0@C87@"
    ),
    # A quarter circle between two straight legs. The arc contributes
    # 300 * pi/2 = 471.239 mm, so 500 + 471.239 + 500 rounds to the 1471 the
    # header states, and the developed-length rule tolerates the 0.239.
    "bar-with-an-arc": (
        "BF2D@HjOCE-DEMO@r312@ib@p4@l1471@n10@e1.306@d12@gB500B@s48@v@Gl500@w0@r300@w90@w0@l500@w0@C73@"
    ),
    # The same arc, but the transition into the next leg is itself bent, which
    # the standard writes as a second angle after the arc's opening angle.
    "bar-with-an-arc-and-a-bend-after-it": (
        "BF2D@HjOCE-DEMO@r312@ib@p5@l1271@n10@e1.129@d12@gB500B@s48@v@Gl400@w45@r300@w90@w45@l400@w0@C87@"
    ),
    # A coupler block with its trailing fields empty. The identifiers are
    # written anyway, which the standard requires.
    "bar-with-a-coupler": (
        "BF2D@HjOCE-DEMO@r312@ib@p6@l200@n1@e0.178@d12@gB500B@s48@v@Gl200@w0@MaSleeveA@bS12@c1@n@o@p@C87@"
    ),
    # A coupler at one end and a thread at the other, so every field of the
    # coupler block carries a value. Three of those values hold an uppercase
    # letter, which must not be read as the start of a new block.
    "bar-with-a-coupler-and-a-thread": (
        "BF2D@HjOCE-DEMO@r312@ib@p7@l200@n1@e0.178@d12@gB500B@s48@v@Gl200@w0@MaSleeveA@bS12@c1@nThreadB@oT13@p2@C82@"
    ),
    # Three bars of one staggered set: same stagger group c20, positions
    # counting within it, and a leg that grows by 300 mm each step.
    "staggered-bar-first": ("BF2D@HjOCE-DEMO@r312@ib@p20.1@l600@n1@e0.533@d12@gB500B@s48@v@c20@Gl250@w90@l350@w0@C75@"),
    "staggered-bar-middle": (
        "BF2D@HjOCE-DEMO@r312@ib@p20.2@l900@n1@e0.799@d12@gB500B@s48@v@c20@Gl250@w90@l650@w0@C86@"
    ),
    "staggered-bar-last": ("BF2D@HjOCE-DEMO@r312@ib@p20.3@l1200@n1@e1.066@d12@gB500B@s48@v@c20@Gl250@w90@l950@w0@C84@"),
    # 250 metres of straight bar off the coil, to keep a five-figure length in
    # the corpus.
    "bar-by-the-running-metre": ("BF2D@HjOCE-DEMO@r312@ib@p8@l250000@n1@e222.000@d12@gB500B@s48@v@Gl250000@w0@C65@"),
    # Spacer positions rather than a bent shape, so a spacer block and no
    # geometry block. Its header is short of 'e' and 'v' on purpose; see
    # HEADER_INCOMPLETE.
    "spacer-positions": "BF2D@HjOCE-DEMO@r312@ib@p9@l1200@n1@d10@gB500B@s40@a1@At6@p150@p600@p1050@C95@",
    # A bar bent out of plane, written as one x/y/z offset per vertex. The
    # geometry opens 'Gx250', where x is the field and not the mesh axis
    # marker that the same two characters spell in a BFMA record.
    "spatial-bar": (
        "BF3D@HjOCE-DEMO@r312@ib@p1@l1400@n10@e1.243@d12@gB500B@s48@v@"
        "Gx250@y0@z0@x0@y300@z0@x0@y0@z300@x0@y-300@z0@x250@y0@z0@C68@"
    ),
    # A column helix on a square section: the planar shape first, then turn
    # and pitch pairs, tighter at the foot and the head than in between.
    "square-helix": (
        "BFWE@HjOCE-DEMO@r312@ib@p1@l25794@n10@e22.905@d12@gB500B@s48@v@"
        "Gl320@w90@l320@w90@l320@w90@l320@w90@n5@g100@n10@g200@n5@g100@C74@"
    ),
    # The same helix on a round section: one full circle and no straight legs.
    "round-helix": (
        "BFWE@HjOCE-DEMO@r312@ib@p2@l31575@n10@e28.039@d12@gB500B@s48@v@Gr250@w360@n5@g100@n10@g200@n5@g100@C86@"
    ),
    # A catalogue mesh, which the header describes completely, so the record
    # carries a header and a checksum and nothing else.
    "stock-mesh": "BFMA@HjOCE-DEMO@r312@ib@p1@l4000@n10@e23.600@gB500B@s48@mQ188@b2000@v@C83@",
    # A drawn mesh, bar by bar. A trailing 'd' on the diameter marks a double
    # bar and its two values are separated by a semicolon.
    "drawn-mesh": (
        "BFMA@HjOCE-DEMO@r312@ib@p2@l4200@n10@e24.240@gB500B@s48@mZM-01@b2600@v@"
        "Yd6d@x150;150@y500;500@l3800;3800@e25,1;200,1@"
        "Yd6d@x650;650@y0;0@l4200;4200@e200,8@"
        "Xd5@x400@y200@l2200@e200,1@"
        "Xd5@x0@y700@l2600@e200,14@C79@"
    ),
    # The same mesh with its longitudinal bars bent, which the geometry block
    # says by marking the axis: 'Gy'.
    "bent-drawn-mesh": (
        "BFMA@HjOCE-DEMO@r312@ib@p3@l4200@n10@e24.240@gB500B@s48@mZM-01@b2600@v@"
        "Gyl150@w-90@l1800@w90@l500@w90@l1800@w-90@l150@w0@"
        "Yd6d@x150;150@y500;500@l3800;3800@e25,1;200,1@"
        "Yd6d@x650;650@y0;0@l4200;4200@e200,8@"
        "Xd5@x400@y200@l2200@e200,1@"
        "Xd5@x0@y700@l2600@e200,14@C94@"
    ),
    # Two accessories. Neither carries a diameter or a steel grade, which is
    # why the cutting summary leaves them out rather than counting them as
    # zero. The drawing index is empty and its identifier is written anyway.
    "spacer-strip": "BFAU@HjOCE-DEMO@r312@i@p1@l2500@n4@e5.500@mSTRIP-16@h150@C79@",
    "support-cage": "BFAU@HjOCE-DEMO@r312@i@p2@l1@n120@e1.250@mCAGE-200-L1@h200@C88@",
    # A lattice girder. Its diagonals are a skewed-bar block, so the record has
    # no geometry block at all.
    "lattice-girder": (
        "BFGT@HjOCE-DEMO@r312@ib@p1@l2400@n1@e4.500@gB500B@mLG-80-90@h90@v@a1@Ex10@y300@l2400@w0@z38@C82@"
    ),
}

#: The one record here whose header omits an identifier its super-group
#: requires. See the module docstring for why it is kept short.
HEADER_INCOMPLETE: frozenset[str] = frozenset({"spacer-positions"})

#: What that record leaves out: the weight and the author.
HEADER_INCOMPLETE_MISSING_FIELDS: list[str] = ["e", "v"]

#: The geometry of ``bar-with-hooked-ends``, and a plausible mistake in it: the
#: overall length written where the middle leg belongs. Two independent checks
#: catch the swap, the checksum and the developed-length arithmetic, which is
#: the point of keeping it.
HOOKED_BAR_GEOMETRY = "Gl150@w180@l500@w180@l150@w0@"
HOOKED_BAR_TOTAL_IN_THE_MIDDLE_LEG = "Gl150@w180@l800@w180@l150@w0@"

#: A lattice girder whose checksum block states a value its own characters do
#: not produce. Nothing else about the record is wrong.
BFGT_MISSTATED_CHECKSUM = (
    "BFGT@HjOCE-DEMO@r312@ib@p1@l2400@n1@e4.500@gB500B@mLG-80-90@h90@v@a1@Ex10@y300@l2400@w0@z38@C72@"
)

#: The value that record states, and the value the checksum rule computes for
#: the same characters.
BFGT_STATED_CHECKSUM = 72
BFGT_CORRECT_CHECKSUM = 82

#: The checksum rule worked through by hand on the shortest record prefix there
#: is, a super-group identifier and the C that opens the checksum block.
#: B + F + 2 + D + @ + C is 66 + 70 + 50 + 68 + 64 + 67 = 385, and 385 is 32 * 12
#: with 1 left over, so the checksum is 96 - 1.
CHECKSUM_ILLUSTRATION = ("BF2D@C", 95)


def fixture_file() -> bytes:
    """The whole corpus as one ABS file, with CRLF record terminators."""
    return "".join(f"{record}\r\n" for record in RECORDS.values()).encode("ascii")


def _prove() -> None:
    """Check every record against the checksum rule, at import.

    Written as an explicit raise rather than an ``assert`` so that it survives
    ``python -O`` and names the record that is wrong.
    """
    for label, record in RECORDS.items():
        if not verify_checksum(record):
            raise AssertionError(f"fixture '{label}' does not reproduce its own checksum: {record}")
    body = BFGT_MISSTATED_CHECKSUM.rsplit("C", 1)[0]
    computed = compute_checksum(body + "C")
    if computed != BFGT_CORRECT_CHECKSUM:
        raise AssertionError(f"the misstated lattice girder computes to {computed}, not {BFGT_CORRECT_CHECKSUM}")
    if verify_checksum(BFGT_MISSTATED_CHECKSUM):
        raise AssertionError("the misstated lattice girder is supposed to fail the checksum rule")
    text, expected = CHECKSUM_ILLUSTRATION
    if compute_checksum(text) != expected:
        raise AssertionError(f"the worked illustration computes to {compute_checksum(text)}, not {expected}")


_prove()
