"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Render the README banner: who the platform is for, and how much of it there is.

Two honeycombs, one above the other and drawn to the same margins so they read as
one field seen at two scales. The upper comb is the cast the Cases hub is built
around, eight company types and fifteen professional roles, each cell a
photograph. The lower comb is every package under `backend/app/modules`, one cell
each, coloured by the category its own manifest declares and shaded by how many
of the others it is wired to.

Nothing in the picture is typed in by hand. Four sources are read:

    frontend/src/features/cases/companyTypes.ts   COMPANY_TYPE_META  (8 entries)
    frontend/src/features/cases/roles.ts          ROLE_META          (15 entries)
    frontend/public/assets/people/                the photographs
    backend/app/modules/*/manifest.py             one per module

so a role added to the product or a module added to the tree shows up on the next
run of this script rather than on the next time somebody remembers it exists.

The cells touch. A hexagon row whose neighbours sit a full row height apart is a
line of separate tiles that happen to be six sided, and an earlier banner drew
exactly that: the triangular notches above and below every cell stayed open and
the picture read as a chain. Pointy top hexagons share edges at one spacing only,
a row step of three quarters of the cell height with every other row inset by half
a cell width, and that is the spacing here. It costs the strip under each cell
where the captions used to sit, so the captions moved inside, into the band
between half height and three quarter height, which is the only part of a pointy
top hexagon still at its full width.

Two module graphs are counted, because they answer different questions and the
gap between them is worth seeing: the `depends` lists in the manifests, which is
what the loader topologically sorts on, and the imports, which is where the
coupling really is. Imports are found with a line anchored regular expression
rather than with `ast` on purpose, because parts of the backend use PEP 695
syntax that only a 3.12 parser accepts and this script should render on whatever
interpreter is at hand. The expression was checked against a full `ast` walk over
the 2120 files a 3.12 parser does accept and the two agree exactly, 704 directed
pairs either way.

The title is not in the picture. It lives in the README above the image, where it
is selectable, searchable and readable by a screen reader.

Usage:

    python scripts/render_readme_banner.py

Requires Pillow, which is already a backend dependency. No browser, no Node.
"""

from __future__ import annotations

import ast
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

REPO = Path(__file__).resolve().parent.parent
CASES = REPO / "frontend" / "src" / "features" / "cases"
PEOPLE = REPO / "frontend" / "public" / "assets" / "people"
MODULES = REPO / "backend" / "app" / "modules"
FONT = REPO / "scripts" / "assets" / "fonts" / "Inter-Variable-Latin.ttf"
OUT = REPO / "docs" / "screenshots" / "banner.png"

# Supersampling for the hexagon shapes and masks. A hexagon drawn straight into
# the final raster has visibly stepped diagonals; drawn four times over and
# reduced, the edges resolve. Only the shapes pay this, not the photographs, and
# text is drawn at final size because FreeType hints it better than a downscale.
SS = 4

WIDTH = 1800
MARGIN = 18
CONTENT = WIDTH - 2 * MARGIN

# Pointy top geometry, twice. Width and height of a regular hexagon are related
# by W = H * sqrt(3) / 2, rows step three quarters of the height, and alternate
# rows are inset by half a width. Change one of these and the cells stop
# touching. The two combs are sized independently to the same content width, so
# their left and right edges line up and the picture reads as one object.
CAST_COLS = 8
CAST_W = CONTENT * 2 // (2 * CAST_COLS + 1)
CAST_H = round(CAST_W * 2 / 3**0.5)
CAST_STEP = CAST_H * 3 // 4

# Widened from 32 on 31.08. The tree reached 193 modules and 32 columns of 6
# rows hold 192, so the render stopped rather than dropping a cell off the
# bottom, which is what the guard below is for. 34 keeps the comb six rows deep
# and leaves room for eleven more before the next widening.
MOD_COLS = 34
MOD_ROWS = 6
MOD_W = CONTENT * 2 // (2 * MOD_COLS + 1)
MOD_H = round(MOD_W * 2 / 3**0.5)
MOD_STEP = MOD_H * 3 // 4

# How far the photograph is pulled toward its accent colour, how much of its
# own colour it keeps, and how far it is then lifted. Enough that the comb reads
# as one palette rather than as a contact sheet, little enough that the faces
# stay faces.
#
# Retuned when the ground went back to white. On a dark ground the tiles needed
# heavy desaturation and no lift at all, because lifting them only greyed them.
# On paper the failure is the opposite one: unlifted tiles with a dark caption
# band under each face sit on white as one slab of shadow, and the faces go into
# it. A little lift and a little more of their own colour keeps them
# photographs. The wash still does the work that matters, which is agreement -
# twenty three pictures shot on different days at different exposures are a
# contact sheet until something makes them one palette.
WASH = 0.24
LIFT = 0.05
KEEP_COLOUR = 0.70

# Where the module colour ramp saturates, in number of modules wired to. Read off
# the measured distribution: the union of the two graphs has a median around five
# and a long thin tail out past a hundred, so scaling against the maximum would
# leave nine cells in ten indistinguishable from an unwired one. Twenty sits near
# the ninetieth percentile, which spreads out the range the modules actually
# occupy while staying monotonic, so a deeper cell is still a more wired one all
# the way up.
RAMP_TOP = 20
RAMP_GAMMA = 0.62

# How far the palest cell is washed toward the ground, and what it is washed
# toward. Both halves matter and the second one is the one that keeps getting
# retuned, because it has to be measured against the ground actually in use.
#
# The floor mixes toward PALE_GROUND and never toward PAPER. A cell washed all
# the way to the ground colour is a hole in the comb, and a hole reads as a
# missing module, so the palest cell has to stop short of the paper. This has
# failed twice in the other direction: 0.90 toward white paper, and 0.74 toward
# a (38, 43, 55) floor on the dark ground, each time leaving the least wired
# cells of the grey and amber buckets uncountable. A banner whose subject is how
# many modules there are cannot afford cells that disappear.
#
# Back on paper the floor is a light tint rather than a dark one, and it is a
# tint and not a grey: mixing toward a slightly blue light stops the amber and
# the red buckets going chalky at their quiet end while staying far enough from
# white to count.
RAMP_FLOOR = 0.58
PALE_GROUND = (208, 216, 230)

# The ground is white, with the faintest possible cool ramp toward the bottom so
# the picture has a top and a bottom rather than floating. It is deliberately
# too slight to name a colour by: anything readable as grey turns the paper into
# a panel, and a panel with its own edges inside a README is worse than a flat
# fill. PAPER stays the name the rest of the file uses for "whatever is behind
# the cells", which is what the hairlines between them are cut out of - so on
# this ground the gutters of both combs are white.
PAPER = (255, 255, 255)
GROUND_TOP = (255, 255, 255)
GROUND_BOTTOM = (241, 245, 250)

INK = (16, 22, 33)
MUTED = (104, 114, 133)
LABEL = (28, 96, 210)

# Hairline between sections. Empty ground was the divider on the dark version,
# where a band of near black reads as one. White has no such band: without a
# rule the module heading sits closer to the photographs above it than to the
# comb it names, and reads as their caption.
RULE = (223, 229, 238)

# One colour per `category` value that at least three modules claim for
# themselves. The six categories with a single member each, and the directories
# carrying no manifest at all, share the last swatch: inventing a colour for a
# category of one would give six specks equal billing with a hundred and nineteen
# modules.
#
# Respaced twice. An early set picked against white mixed a 216 blue with a 148
# teal and a 158 grey, three different luminances doing the same job, and the
# comb read as a rainbow rather than as a sorted field; the dark set that
# replaced it put all seven at one chroma and one luminance band. That band was
# chosen to sit on black, and every one of those swatches is a shade too light
# to hold on paper, so the rule is kept and the band is moved: still one chroma
# and one weight, still far enough apart in hue to count, a step deeper.
#
# The last two are the pair to watch. Enterprise and Other are both greys, three
# modules and nine, and on the dark ground they were four points of luminance
# apart, which is not a difference a reader can use in a legend. Enterprise is
# now a slate with some blue in it and Other a true neutral, so the legend can
# be read without counting cells.
BUCKETS: list[tuple[str, str, tuple[int, int, int]]] = [
    ("core", "Core", (46, 112, 240)),
    ("business", "Business", (13, 165, 148)),
    ("regional", "Regional", (226, 142, 30)),
    ("extension", "Extension", (139, 108, 240)),
    ("controls", "Controls", (230, 71, 96)),
    ("enterprise", "Enterprise", (86, 106, 138)),
    ("__other__", "Other", (160, 168, 180)),
]

# --------------------------------------------------------------------------- #
# Vocabularies, read from the TypeScript sources that own them
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cell:
    """One captioned hexagon: a photograph, a caption and an accent colour."""

    ident: str
    caption: tuple[str, ...]
    photo: Path
    accent: tuple[int, int, int]


def _read_ids(source: Path, array_name: str) -> list[str]:
    """The `id:` values of every entry in a `const <array_name>: X[] = [...]` literal.

    Parsing the source rather than hardcoding the ids is the whole point of the
    script: a role added to `roles.ts` has to show up here on the next run without
    anyone remembering that this file exists.
    """
    text = source.read_text(encoding="utf-8")
    start = text.index(f"export const {array_name}")
    end = text.index("\n];", start)
    # Digits are in the character class so that an id like `tier-2-contractor` is
    # READ and then rejected by `_require`, rather than being skipped as if it had
    # never been written. An id this regex cannot match is invisible twice over:
    # its tile goes missing, and because `_accents` pairs ids with tints by
    # position it also shifts the accent of every entry after it.
    return re.findall(r"^\s{4}id: '([a-z0-9-]+)',$", text[start:end], flags=re.MULTILINE)


# The two cast headings, and the counts they spell out. These are the reason the
# script cannot simply draw whatever it finds: "FIFTEEN PROFESSIONAL ROLES" over
# fourteen hexagons is a caption that lies, and nothing downstream would catch it.
# The module heading needs no such guard because its number is not written here at
# all, it is counted on the way past.
EXPECTED_COMPANIES = 8
EXPECTED_ROLES = 15
HEAD_CAST = "EIGHT COMPANY TYPES, FIFTEEN PROFESSIONAL ROLES"

# Short captions. The `labelDefault` strings in the sources are written for a
# selector row with a full line to itself ("Project / construction management
# firm"); inside a hexagon they have about two short lines, so the banner keeps
# its own shortened forms and asserts below that it has one for every id.
COMPANY_CAPTIONS: dict[str, tuple[str, ...]] = {
    "general-contractor": ("General", "contractor"),
    "subcontractor": ("Specialist", "subcontractor"),
    "cost-consultant": ("Cost consultancy", "/ QS"),
    "designer": ("Design /", "engineering"),
    "developer-client": ("Developer", "/ client"),
    "project-manager": ("Project", "management"),
    "bim-consultant": ("BIM / digital", "consultancy"),
    "owner-operator": ("Owner /", "operator (FM)"),
}

ROLE_CAPTIONS: dict[str, tuple[str, ...]] = {
    "estimator": ("Estimator",),
    "quantity-surveyor": ("Quantity", "surveyor"),
    "site-manager": ("Site", "manager"),
    "project-manager": ("Project", "manager"),
    "bim-coordinator": ("BIM", "coordinator"),
    "procurement-buyer": ("Procurement", "/ buyer"),
    "planner": ("Planner /", "scheduler"),
    "hse-officer": ("Health &", "safety"),
    "design-lead": ("Design", "lead"),
    "document-controller": ("Document", "controller"),
    "commercial-manager": ("Commercial", "manager"),
    "accountant": ("Accountant",),
    "contract-administrator": ("Contract", "administrator"),
    "finance-manager": ("Finance", "manager"),
    "foreman": ("Foreman /", "supervisor"),
}

# Company type -> photo stem. Copied from COMPANY_THUMB_ALIASES in caseFaces.ts,
# which points each company type at its archetype's picture; ids that already
# name a stem need no entry there and get none here.
COMPANY_STEM: dict[str, str] = {
    "general-contractor": "general-contractor",
    "subcontractor": "subcontractor",
    "cost-consultant": "estimator",
    "designer": "architecture-engineering",
    "developer-client": "real-estate-developer",
    "project-manager": "construction-manager",
    "bim-consultant": "bim-vdc",
    "owner-operator": "facility-manager",
}

# Role -> portrait stem. This mapping is the banner's own and deliberately does
# NOT live in caseFaces.ts: that module casts by company type on purpose, and its
# header says in as many words not to make it read `Playbook.roles`. Here the two
# axes are both being drawn at once, so each role needs a face of its own, and
# the constraint is only that the fifteen are distinct - a reader comparing two
# neighbouring tiles must not see the same person under two job titles.
ROLE_STEM: dict[str, str] = {
    "estimator": "estimator",
    "quantity-surveyor": "quality-manager",
    "site-manager": "site-supervisor",
    "project-manager": "construction-manager",
    "bim-coordinator": "bim-vdc",
    "procurement-buyer": "procurement-manager",
    "planner": "scheduler-planner",
    "hse-officer": "hse-manager",
    "design-lead": "architecture-engineering",
    "document-controller": "government-agency",
    "commercial-manager": "commercial-manager",
    "accountant": "owner-client",
    "contract-administrator": "design-build",
    "finance-manager": "real-estate-developer",
    "foreman": "subcontractor",
}

# Accent colours, the 600 weight of the Tailwind hue each source file names in its
# tint, so the banner and the app tint the same concept the same way.
TAILWIND_600: dict[str, tuple[int, int, int]] = {
    "blue": (37, 99, 235),
    "orange": (234, 88, 12),
    "green": (22, 163, 74),
    "purple": (147, 51, 234),
    "pink": (219, 39, 119),
    "yellow": (202, 138, 4),
    "indigo": (79, 70, 229),
    "cyan": (8, 145, 178),
    "amber": (217, 119, 6),
    "teal": (13, 148, 136),
    "violet": (124, 58, 237),
    "emerald": (5, 150, 105),
    "sky": (2, 132, 199),
    "red": (220, 38, 38),
    "slate": (71, 85, 105),
    "fuchsia": (192, 38, 211),
    "rose": (225, 29, 72),
}


def _accents(source: Path, array_name: str, ids: list[str]) -> dict[str, tuple[int, int, int]]:
    """The accent colour per entry, taken from the Tailwind hue in its `tint.text`.

    `tint.text` is a literal like `text-amber-600 dark:text-amber-400`; the hue is
    what the banner needs and the weights are the app's business.
    """
    text = source.read_text(encoding="utf-8")
    start = text.index(f"export const {array_name}")
    # Bounded at the end of the literal, like `_read_ids`: an unbounded scan would
    # happily read a tint belonging to some later constant in the same file. Ids
    # and tints are paired by POSITION, so one stray or missing match silently
    # recolours every entry after it - hence `!=` rather than `<`.
    end = text.index("\n];", start)
    hues = re.findall(r"^\s+text: 'text-([a-z]+)-\d00 ", text[start:end], flags=re.MULTILINE)
    if len(hues) != len(ids):
        raise SystemExit(f"{source.name}: found {len(hues)} tints for {len(ids)} ids")
    unknown = sorted({h for h in hues if h not in TAILWIND_600})
    if unknown:
        raise SystemExit(f"{source.name}: no RGB for Tailwind hue(s) {', '.join(unknown)}")
    return {i: TAILWIND_600[h] for i, h in zip(ids, hues, strict=True)}


def build_cells() -> tuple[list[Cell], list[Cell]]:
    """The eight company types and the fifteen roles, in source order."""
    company_ids = _read_ids(CASES / "companyTypes.ts", "COMPANY_TYPE_META")
    role_ids = _read_ids(CASES / "roles.ts", "ROLE_META")
    if not company_ids or not role_ids:
        raise SystemExit("could not parse the vocabularies out of the cases sources")

    # `_require` only fires on an id it has never seen, so it catches an ADDITION
    # and nothing else: delete a role and the banner quietly draws fourteen tiles
    # under a heading that reads FIFTEEN. The heading spells its counts out in
    # words, so the counts are part of the drawing and belong under a guard.
    if (len(company_ids), len(role_ids)) != (EXPECTED_COMPANIES, EXPECTED_ROLES):
        raise SystemExit(
            f"the vocabularies moved: {len(company_ids)} company types and {len(role_ids)} roles, "
            f"but this script draws a heading for {EXPECTED_COMPANIES} and {EXPECTED_ROLES}. "
            "Update HEAD_CAST, the expected counts and the captions together."
        )

    company_accents = _accents(CASES / "companyTypes.ts", "COMPANY_TYPE_META", company_ids)
    role_accents = _accents(CASES / "roles.ts", "ROLE_META", role_ids)

    companies, roles = [], []
    for ident in company_ids:
        _require(ident, COMPANY_CAPTIONS, COMPANY_STEM, "company type")
        companies.append(
            Cell(
                ident,
                COMPANY_CAPTIONS[ident],
                PEOPLE / f"cmt-{COMPANY_STEM[ident]}.webp",
                company_accents[ident],
            )
        )
    for ident in role_ids:
        _require(ident, ROLE_CAPTIONS, ROLE_STEM, "role")
        roles.append(
            Cell(
                ident,
                ROLE_CAPTIONS[ident],
                PEOPLE / f"prf-{ROLE_STEM[ident]}.webp",
                role_accents[ident],
            )
        )

    if len({c.photo for c in roles}) != len(roles):
        raise SystemExit("two roles share a portrait; give each its own face in ROLE_STEM")
    for cell in companies + roles:
        if not cell.photo.exists():
            raise SystemExit(f"{cell.ident}: no photograph at {cell.photo}")
    return companies, roles


def _require(ident: str, captions: dict, stems: dict, kind: str) -> None:
    """Fail loudly when a vocabulary grew and this file did not follow it."""
    if ident not in captions:
        raise SystemExit(f"new {kind} '{ident}' has no caption in this script")
    if ident not in stems:
        raise SystemExit(f"new {kind} '{ident}' has no photo stem in this script")


# --------------------------------------------------------------------------- #
# The modules, read from the manifests that own them
# --------------------------------------------------------------------------- #


@dataclass
class Module:
    """One directory under `backend/app/modules`."""

    ident: str
    manifest_name: str | None
    category: str
    depends: list[str] = field(default_factory=list)


@dataclass
class Survey:
    """Everything the lower comb is drawn from, counted once."""

    modules: list[Module]
    declared: set[tuple[str, str]]
    imports: set[tuple[str, str]]
    degree: Counter


_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+app\.modules\.([a-z0-9_]+)|import[ \t]+app\.modules\.([a-z0-9_]+))",
    re.MULTILINE,
)


def _manifest_of(path: Path) -> tuple[str | None, str, list[str]]:
    """The name, category and depends list of the `ModuleManifest(...)` in a file.

    Parsed, never imported. Importing a manifest pulls in `app.core.module_loader`
    and through it most of the application, and a banner has no business needing
    the backend to be importable.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ModuleManifest":
            kw = {k.arg: k.value for k in node.keywords if k.arg}

            def read(key: str, fallback):
                return ast.literal_eval(kw[key]) if key in kw else fallback

            return (
                read("name", None),
                read("category", "__other__"),
                read("depends", None) or [],
            )
    return None, "__other__", []


def survey() -> Survey:
    """Read the module tree and both dependency graphs."""
    idents = sorted(p.name for p in MODULES.iterdir() if p.is_dir() and p.name != "__pycache__")
    known = set(idents)

    modules: list[Module] = []
    by_manifest_name: dict[str, str] = {}
    for ident in idents:
        manifest = MODULES / ident / "manifest.py"
        if manifest.exists():
            name, category, depends = _manifest_of(manifest)
        else:
            name, category, depends = None, "__other__", []
        if name:
            by_manifest_name[name] = ident
        modules.append(Module(ident, name, category, depends))

    # Declared dependencies. An entry naming something no manifest declares stops
    # the run: a dropped edge would quietly lower a number the README states, and
    # nothing downstream would notice it had gone.
    declared: set[tuple[str, str]] = set()
    for module in modules:
        for target in module.depends:
            other = by_manifest_name.get(target)
            if other is None:
                raise SystemExit(
                    f"{module.ident}/manifest.py declares a dependency on {target!r}, which no "
                    f"manifest in the tree names. Fix the manifest, or the count in the banner "
                    f"goes quietly wrong."
                )
            if other != module.ident:
                declared.add(tuple(sorted((module.ident, other))))

    imports: set[tuple[str, str]] = set()
    for ident in idents:
        for source in (MODULES / ident).rglob("*.py"):
            if "__pycache__" in source.parts:
                continue
            text = source.read_text(encoding="utf-8", errors="replace")
            for from_form, import_form in _IMPORT.findall(text):
                target = from_form or import_form
                if target in known and target != ident:
                    imports.add(tuple(sorted((ident, target))))

    degree: Counter = Counter()
    for a, b in declared | imports:
        degree[a] += 1
        degree[b] += 1
    return Survey(modules, declared, imports, degree)


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def _hexagon(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    """A pointy top hexagon in the box (x, y) to (x + w, y + h).

    Full width holds only between h/4 and 3h/4; the cell tapers to a point above
    and below that band, so anything placed outside it runs off the sides.
    """
    return [
        (x + w / 2, y),
        (x + w, y + h / 4),
        (x + w, y + h * 3 / 4),
        (x + w / 2, y + h),
        (x, y + h * 3 / 4),
        (x, y + h / 4),
    ]


def _hex_mask(w: int, h: int, inset: float) -> Image.Image:
    """An antialiased alpha mask of a pointy top hexagon, drawn oversized.

    `inset` shrinks the shape about its centre. Cells that share an edge and are
    filled to that edge merge into one another, and a comb of photographs with no
    wall between them is a collage; a hairline of paper is what makes the cells
    read as cells while they still touch.
    """
    big = Image.new("L", (w * SS, h * SS), 0)
    points = [
        ((px - w / 2) * (1 - inset) + w / 2, (py - h / 2) * (1 - inset) + h / 2) for px, py in _hexagon(0, 0, w, h)
    ]
    ImageDraw.Draw(big).polygon([(px * SS, py * SS) for px, py in points], fill=255)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    if not FONT.exists():
        raise SystemExit(
            f"the banner face is missing: {FONT}\n"
            f"It is tracked in the repository on purpose. A missing font does not fail, it "
            f"substitutes, and a banner set in whatever face happened to be installed is one "
            f"nobody else can reproduce."
        )
    face = ImageFont.truetype(str(FONT), size)
    # Optical size axis first, then weight. Inter's optical axis runs 14 to 32:
    # display sizes want the larger end, running text the smaller.
    face.set_variation_by_axes([32.0 if size >= 40 else 14.0, float(weight)])
    return face


def _tile(cell: Cell, mask: Image.Image) -> Image.Image:
    """One hexagon: the photograph, cropped to fill, washed in the cell's accent."""
    photo = Image.open(cell.photo).convert("RGB")

    # Cover, then take the top middle rather than the centre: these are portraits
    # and the head sits high in the frame, so a centred crop of a 340x480 lands on
    # the chest.
    scale = max(CAST_W / photo.width, CAST_H / photo.height)
    grown = (max(1, round(photo.width * scale)), max(1, round(photo.height * scale)))
    photo = photo.resize(grown, Image.Resampling.LANCZOS)
    left = (photo.width - CAST_W) // 2
    top = round((photo.height - CAST_H) * 0.10)
    photo = photo.crop((left, top, left + CAST_W, top + CAST_H))

    # Desaturate first, then wash toward the cell's accent. In the other order
    # the desaturation eats the accent it was just given and every tile comes
    # back the same grey.
    photo = ImageEnhance.Color(photo).enhance(KEEP_COLOUR)
    photo = Image.blend(photo, Image.new("RGB", photo.size, cell.accent), WASH)
    if LIFT:
        photo = Image.blend(photo, Image.new("RGB", photo.size, (255, 255, 255)), LIFT)

    # The caption sits on the picture now that the rows have closed up, so the
    # bottom of the cell is darkened to carry white text. The ramp reaches most of
    # its weight BEFORE the caption starts rather than at the bottom of the cell:
    # text set on the first few percent of a gradient is text on the bare
    # photograph, and half of these photographs are pale. It also starts above the
    # caption band rather than at its edge, because a hard line across a face
    # reads as damage to the photograph.
    scrim = Image.new("L", (CAST_W, CAST_H), 0)
    pen = ImageDraw.Draw(scrim)
    fade_from, fade_to = round(CAST_H * 0.30), round(CAST_H * 0.56)
    for y in range(fade_from, CAST_H):
        ramp = min(1.0, (y - fade_from) / max(1, fade_to - fade_from))
        pen.line((0, y, CAST_W, y), fill=round(225 * ramp**0.85))
    photo = Image.composite(Image.new("RGB", photo.size, (9, 14, 26)), photo, scrim)

    tile = Image.new("RGBA", (CAST_W, CAST_H), (0, 0, 0, 0))
    tile.paste(photo, (0, 0), mask)
    return tile


def draw_cast(canvas: Image.Image, pen: ImageDraw.ImageDraw, rows: list[list[Cell]], top: int) -> int:
    """Draw the photograph comb. Returns the bottom y."""
    mask = _hex_mask(CAST_W, CAST_H, inset=0.018)
    caption_font = _font(21, 600)
    line_height = 25
    for index, row in enumerate(rows):
        indent = (CAST_W // 2) if index % 2 else 0
        y = top + index * CAST_STEP
        for column, cell in enumerate(row):
            x = MARGIN + indent + column * CAST_W
            tile = _tile(cell, mask)
            canvas.paste(tile, (x, y), tile)

            # The caption sits in the band where the hexagon is at full width.
            # Below three quarter height the shape tapers to a point and text put
            # there runs off both sides of it, which is the failure the captions
            # were moved inside to avoid in the first place.
            centre = x + CAST_W // 2
            baseline = y + round(CAST_H * 0.745) - line_height * len(cell.caption)
            for line in cell.caption:
                pen.text(
                    (centre, baseline),
                    line,
                    font=caption_font,
                    fill=(255, 255, 255),
                    anchor="ma",
                )
                baseline += line_height
    return top + (len(rows) - 1) * CAST_STEP + CAST_H


def _bucket_index(category: str) -> int:
    for i, (key, _, _) in enumerate(BUCKETS):
        if key == category:
            return i
    return len(BUCKETS) - 1


def _tint(base: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """The bucket colour, from a dark wash at t=0 to the full colour at t=1."""
    pale = [round(c + (g - c) * RAMP_FLOOR) for c, g in zip(base, PALE_GROUND, strict=True)]
    return (
        round(pale[0] + (base[0] - pale[0]) * t),
        round(pale[1] + (base[1] - pale[1]) * t),
        round(pale[2] + (base[2] - pale[2]) * t),
    )


def draw_modules(data: Survey) -> Image.Image:
    """The module honeycomb, sorted by bucket and then by how wired each one is."""
    order = sorted(
        data.modules,
        key=lambda m: (_bucket_index(m.category), -data.degree[m.ident], m.ident),
    )
    if len(order) > MOD_COLS * MOD_ROWS:
        raise SystemExit(
            f"{len(order)} modules will not fit {MOD_ROWS} rows of {MOD_COLS}. "
            f"Widen the comb rather than letting cells fall off the bottom."
        )
    comb_w = MOD_COLS * MOD_W + MOD_W // 2
    comb_h = (MOD_ROWS - 1) * MOD_STEP + MOD_H

    # Transparent, not filled: the ground behind this comb is a gradient, and a
    # flat rectangle the width of the picture would show its own edges against
    # it. The hairline between cells is now cut out of the tile rather than
    # painted over it, which is the same wall by the other method.
    canvas = Image.new("RGBA", (comb_w * SS, comb_h * SS), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)
    for index, module in enumerate(order):
        row, col = divmod(index, MOD_COLS)
        # Boustrophedon: every other row runs right to left, so the ordering is
        # continuous across the turn. Filled strictly left to right, each category
        # ends pale at the right margin and the next starts dark at the left,
        # which puts a hard vertical seam down the picture and reads as a
        # rendering fault rather than as the category boundary it is.
        if row % 2:
            col = MOD_COLS - 1 - col
        x = (col * MOD_W + (MOD_W // 2 if row % 2 else 0)) * SS
        y = row * MOD_STEP * SS
        t = min(1.0, (data.degree[module.ident] / RAMP_TOP) ** RAMP_GAMMA)
        fill = _tint(BUCKETS[_bucket_index(module.category)][2], t)
        pen.polygon(
            _hexagon(x, y, MOD_W * SS, MOD_H * SS),
            fill=(*fill, 255),
            outline=(0, 0, 0, 0),
            width=2 * SS,
        )
    return canvas.resize((comb_w, comb_h), Image.Resampling.LANCZOS)


def draw_label(pen: ImageDraw.ImageDraw, text: str, top: int) -> int:
    """A letter spaced label over a comb, so the reader knows what it is.

    A small filled hexagon leads it. The picture is two honeycombs and its
    labels were two lines of grey type that could have belonged to anything; one
    cell of the same shape, at text size, ties the label to what it names.
    """
    font = _font(21, 650)
    bullet = 13
    pen.polygon(_hexagon(MARGIN, top + 3, bullet, round(bullet * 2 / 3**0.5)), fill=LABEL)
    x = float(MARGIN + bullet + 11)
    for character in text:
        pen.text((x, top), character, font=font, fill=LABEL)
        x += pen.textlength(character, font=font) + 1.9
    return top + 25


def draw_rule(pen: ImageDraw.ImageDraw, top: int) -> int:
    """A hairline across the content width. Returns the bottom y."""
    pen.line((MARGIN, top, WIDTH - MARGIN - 1, top), fill=RULE, width=1)
    return top + 1


def draw_legend(pen: ImageDraw.ImageDraw, data: Survey, top: int) -> int:
    """A swatch and a count for each bucket, laid out across the full width."""
    counts = Counter(_bucket_index(m.category) for m in data.modules)
    label_font = _font(22, 600)
    count_font = _font(22, 400)

    chip_w, chip_h = 22, 25
    entries = []
    for i, (_, label, colour) in enumerate(BUCKETS):
        count = str(counts[i])
        span = chip_w + 10 + pen.textlength(label, font=label_font) + 7 + pen.textlength(count, font=count_font)
        entries.append((label, count, colour, span))

    gap = (CONTENT - sum(e[3] for e in entries)) / (len(entries) - 1)
    x = float(MARGIN)
    for label, count, colour, _ in entries:
        pen.polygon(_hexagon(x, top + 1, chip_w, chip_h), fill=colour)
        x += chip_w + 10
        pen.text((x, top), label, font=label_font, fill=INK)
        x += pen.textlength(label, font=label_font) + 7
        pen.text((x, top), count, font=count_font, fill=MUTED)
        x += pen.textlength(count, font=count_font) + gap
    return top + chip_h


def _ground(width: int, height: int) -> Image.Image:
    """The paper everything is drawn on: white, with one very slight ramp.

    One vertical ramp is enough to give the picture a top and a bottom; anything
    more elaborate competes with the two combs, which are the subject. Kept
    almost invisible here on purpose, because on white the ramp has a second job
    it did not have on black - it must not turn the image into a grey panel with
    edges of its own sitting inside a white README.
    """
    ground = Image.new("RGB", (1, height))
    pen = ImageDraw.Draw(ground)
    for y in range(height):
        t = y / max(1, height - 1)
        pen.point(
            (0, y),
            fill=tuple(round(a + (b - a) * t) for a, b in zip(GROUND_TOP, GROUND_BOTTOM, strict=True)),
        )
    return ground.resize((width, height), Image.Resampling.BILINEAR)


def render(companies: list[Cell], roles: list[Cell], data: Survey) -> None:
    # Eight companies, then the fifteen roles as eight and seven, so each row is
    # one group rather than a group boundary landing mid row.
    cast_rows = [companies, roles[:8], roles[8:]]
    cast_h = (len(cast_rows) - 1) * CAST_STEP + CAST_H
    comb = draw_modules(data)

    lead_font = _font(26, 500)
    note_font = _font(23, 400)
    label_h, after_label = 25, 11
    # Hand kept in step with the sequence of draws below, section by section, so
    # that a change to one has an obvious counterpart here.
    height = (
        20  # top margin
        + label_h
        + after_label
        + cast_h
        + 26  # cast comb to rule
        + 1  # rule
        + 25  # rule to the module heading
        + label_h
        + after_label
        + comb.height
        + 26  # module comb to legend
        + 23  # legend
        + 22  # legend to rule
        + 1  # rule
        + 20  # rule to the lead line
        + 32
        + 11
        + 29
        + 26  # bottom margin
    )

    canvas = _ground(WIDTH, height)
    pen = ImageDraw.Draw(canvas)

    modules = sum(1 for m in data.modules if m.manifest_name)
    libraries = len(data.modules) - modules

    y = draw_label(pen, HEAD_CAST, 20) + after_label
    y = draw_rule(pen, draw_cast(canvas, pen, cast_rows, y) + 26) + 25
    y = draw_label(pen, f"{modules} BACKEND MODULES, WIRED TO EACH OTHER", y) + after_label
    canvas.paste(comb, (MARGIN, y), comb)
    y = draw_legend(pen, data, y + comb.height + 26)

    busiest = ", ".join(ident for ident, _ in data.degree.most_common(3))
    lead = (
        f"{modules} backend modules  ·  {len(data.declared)} dependencies declared in their "
        f"manifests  ·  {len(data.imports)} imports between them"
    )
    note = (
        f"{libraries} of the lower cells are shared libraries, not modules. Colour depth is how many "
        f"others each is wired to, deepest at {busiest}."
    )
    y = draw_rule(pen, y + 22) + 20
    pen.text((MARGIN, y), lead, font=lead_font, fill=INK)
    pen.text((MARGIN, y + 32 + 11), note, font=note_font, fill=MUTED)

    # A caption that runs off the edge is a caption nobody finishes reading, and
    # the width it needs depends on the numbers, which change with the tree.
    for name, text, face in (("lead", lead, lead_font), ("note", note, note_font)):
        over = pen.textlength(text, font=face) - CONTENT
        if over > 0:
            raise SystemExit(f"the {name} line overruns the banner by {over:.0f}px: {text}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Saved as full colour on purpose, and it is worth saying why, because the
    # file is a megabyte and quantising it looks like free money. It is not: a
    # 256 colour palette is dominated by the photographs, and the module comb's
    # hues get remapped around them. Measured, the legend swatch for Extension
    # came back blue, Controls came back red and Regional came back brown, so
    # the key stopped matching the cells it labels. A smaller file that lies
    # about its own legend is not an optimisation.
    canvas.save(OUT, optimize=True)

    degrees = [data.degree[m.ident] for m in data.modules]
    unmanifested = [m.ident for m in data.modules if m.manifest_name is None]
    print(f"wrote {OUT.relative_to(REPO)}  {canvas.width}x{canvas.height}  {OUT.stat().st_size // 1024} KB")
    print(f"  cast   {len(companies)} companies + {len(roles)} roles, cell {CAST_W}x{CAST_H}, step {CAST_STEP}")
    print(f"  comb   {len(data.modules)} cells in {MOD_ROWS} rows of {MOD_COLS}, cell {MOD_W}x{MOD_H}")
    print(f"  modules with a manifest {modules}, shared libraries {libraries}")
    print(f"  declared dependencies   {len(data.declared)}")
    print(f"  import links            {len(data.imports)}")
    print(f"  wired to at least one   {sum(1 for d in degrees if d)}")
    print(f"  degree median {statistics.median(degrees)}  mean {statistics.mean(degrees):.1f}  max {max(degrees)}")
    if unmanifested:
        # Said out loud rather than raised. The loader discovers modules by finding
        # a manifest, so a directory without one is invisible to it and drops out
        # with no error at all; that silence is the reason to print it.
        print(f"  no manifest, drawn in the Other bucket: {', '.join(unmanifested)}")


if __name__ == "__main__":
    render(*build_cells(), survey())
