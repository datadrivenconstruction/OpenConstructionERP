# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which bill positions a seeded tender package covers, decided by trade.

A demo pack names its tender packages in its own language ("Innenausbau:
Trockenbau, Doppelboden, Akustikdecken, Bodenbeläge, Türen", "Building
Envelope (Curtain Wall & Roofing)"), and the bill carries positions classified
under the project's standard. The installer used to cut the bill into one
contiguous, money-balanced slice per package, so a package called interior
fit-out could hold the roof slab and the PV plant while the drywall sat in
another package. Here both sides are put into one trade vocabulary instead:

* a position's trade comes from its classification code where the standard
  is one we can read (DIN 276 cost group, MasterFormat division, NRM element),
  else from the trade bucket the resource build-up already assigned it, else
  from words in its description;
* a package's trades come from the words of its name and description in the
  languages the shipped packs are written in (most carry an English gloss),
  and a package that names DIN 276 groups outright ("KG 510+520") covers
  exactly those groups.

A position goes to the package that names its trade most strongly (in the
name beats in the description; ties go to the package whose words share the
most with the position, then to the narrower package). A trade no package
names goes to the main-contract package when there is one, then to a package
that customarily carries it (the structure contractor takes the site set-up
and the pit), and otherwise stays out of every package: a demo bill tenders
some trades and not others, as a real one does.

The second half of the module dates the packages. A seeded package used to
keep the status its pack wrote ("draft" next to three submitted bids) and a
deadline fixed to the calendar, so a demo opened months later showed every
tender long closed. Statuses are now made to agree with the bids, and every
date is counted from the day the demo is installed: closed packages closed
in the recent past, open ones close in the coming weeks, and each pack keeps
one package still out with an invited firm that has not quoted yet.

Pure functions only, so the installer and the tests call the same code.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

#: The trade vocabulary both sides are mapped into.
TRADES: tuple[str, ...] = (
    "prelims",
    "earthworks",
    "piling",
    "structure",
    "masonry",
    "envelope",
    "roofing",
    "fitout",
    "mechanical",
    "fire",
    "electrical",
    "solar",
    "storage",
    "lifts",
    "external",
)

# Trade bucket of ``demo_projects._enrich_position_metadata`` ("CWICR-DRY-001"
# reads "DRY") -> trade. GEN is the bucket for "no keyword matched" and is
# deliberately absent, so such a position is read from its words instead.
_BUCKET_TRADE: dict[str, str] = {
    "ACO": "fitout",
    "CLD": "envelope",
    "CON": "structure",
    "DOR": "fitout",
    "DRY": "fitout",
    "ELE": "electrical",
    "ELV": "lifts",
    "ENV": "envelope",
    "EQP": "mechanical",
    "ERT": "earthworks",
    "EXT": "external",
    "FIN": "fitout",
    "FIT": "fitout",
    "FLR": "fitout",
    "FPR": "fire",
    "FRM": "structure",
    "FTC": "structure",
    "GLT": "structure",
    "INS": "envelope",
    "LAN": "external",
    "MAS": "masonry",
    "MEC": "mechanical",
    "MHE": "mechanical",
    "PAV": "external",
    "PIL": "piling",
    "PLB": "mechanical",
    "PLT": "fitout",
    "PNT": "fitout",
    "PRE": "prelims",
    "REF": "mechanical",
    "REN": "solar",
    "ROF": "roofing",
    "SCR": "fitout",
    "SIT": "external",
    "SPE": "fitout",
    "STL": "structure",
    "STR": "structure",
    "TIL": "fitout",
    "TMB": "structure",
    "WIN": "envelope",
    "WPR": "envelope",
}

# DIN 276 cost groups, read by longest prefix. Groups 330 to 360 hold more
# than one trade under one heading (load-bearing and non-load-bearing walls,
# slab and floor finish), so only their three-digit children are listed.
_DIN276: dict[str, str] = {
    "1": "prelims",
    "2": "prelims",
    "31": "earthworks",
    "32": "structure",
    "331": "structure",
    "332": "envelope",
    "333": "structure",
    "334": "envelope",
    "335": "envelope",
    "336": "fitout",
    "337": "envelope",
    "338": "envelope",
    "339": "envelope",
    "341": "structure",
    "342": "fitout",
    "343": "structure",
    "344": "fitout",
    "345": "fitout",
    "346": "fitout",
    "349": "fitout",
    "351": "structure",
    "352": "fitout",
    "353": "fitout",
    "359": "fitout",
    "361": "structure",
    "362": "roofing",
    "363": "roofing",
    "364": "fitout",
    "369": "roofing",
    "37": "fitout",
    "39": "prelims",
    "41": "mechanical",
    "42": "mechanical",
    "43": "mechanical",
    "44": "electrical",
    "45": "electrical",
    "46": "lifts",
    "47": "mechanical",
    "474": "fire",
    "48": "electrical",
    "49": "mechanical",
    "5": "external",
    "6": "fitout",
    "7": "prelims",
    "8": "prelims",
}
_DIN276_HEADINGS = frozenset({"3", "33", "34", "35", "36"})

# MasterFormat divisions, then the sections that leave their division's trade.
_MASTERFORMAT: dict[str, str] = {
    "01": "prelims",
    "02": "earthworks",
    "03": "structure",
    "04": "masonry",
    "05": "structure",
    "06": "structure",
    "06 4": "fitout",
    "07": "envelope",
    "07 5": "roofing",
    "07 6": "roofing",
    "07 7": "roofing",
    "08": "envelope",
    "08 1": "fitout",
    "08 7": "fitout",
    "09": "fitout",
    "10": "fitout",
    "11": "fitout",
    "12": "fitout",
    "13": "structure",
    "14": "lifts",
    "21": "fire",
    "22": "mechanical",
    "23": "mechanical",
    "25": "electrical",
    "26": "electrical",
    "26 31": "solar",
    "27": "electrical",
    "28": "fire",
    "31": "earthworks",
    "31 6": "piling",
    "32": "external",
    "33": "external",
    "34": "external",
    "35": "external",
    "40": "mechanical",
    "41": "mechanical",
    "44": "mechanical",
    "46": "mechanical",
    "48": "solar",
}

# NRM 1 elements.
_NRM: dict[str, str] = {
    "0": "earthworks",
    "1": "structure",
    "2.1": "structure",
    "2.2": "structure",
    "2.3": "roofing",
    "2.4": "structure",
    "2.5": "envelope",
    "2.6": "envelope",
    "2.7": "fitout",
    "2.8": "fitout",
    "3": "fitout",
    "4": "fitout",
    "5": "mechanical",
    "5.8": "electrical",
    "5.10": "lifts",
    "5.11": "fire",
    "5.12": "electrical",
    "6": "structure",
    "7": "fitout",
    "8": "external",
    "9": "prelims",
    "10": "prelims",
    "11": "prelims",
    "12": "prelims",
    "13": "prelims",
    "14": "prelims",
}

# Words that promise a trade, in the languages the shipped packs write their
# packages in. A Latin word matches at the start of a word ("structur" finds
# "structure" and "structural"); a CJK word matches anywhere.
_WORDS: dict[str, tuple[str, ...]] = {
    "prelims": ("prelim", "site setup", "baustelleneinrichtung", "installation de chantier", "preliminares"),
    "earthworks": (
        "earthwork",
        "excavat",
        "shoring",
        "dewater",
        "erdbau",
        "erdarbeit",
        "baugrube",
        "verbau",
        "aushub",
        "terrassement",
        "étançonnement",
        "movimento de terra",
        "contenção",
        "enabling",
        "ground improvement",
        "pit support",
        "基坑",
        "土方",
        "ground",
        "graving",
        "udgravning",
        "schakt",
        "spunt",
        "spons",
        "bouwkuip",
        "roboty ziemne",
        "obudowa wykopu",
        "földmunka",
        "εκσκαφ",
        "земляные",
        "земляні",
        "нулевой цикл",
        "stan zerowy",
        "terasamente",
        "根切",
        "山留め",
    ),
    "piling": (
        "piling",
        "pile",
        "pfahl",
        "pieux",
        "estacas",
        "fondations profondes",
        "cimentación profunda",
        "桩",
        "peling",
        "paelning",
        "palen",
        "cölöp",
        "свай",
        "палі",
        "杭",
    ),
    "structure": (
        "structur",
        "rohbau",
        "concrete",
        "beton",
        "béton",
        "concreto",
        "gründung",
        "foundation",
        "fondation",
        "fundaç",
        "cimentación",
        "substructure",
        "superstructure",
        "frame",
        "skelettbau",
        "decken",
        "kerne",
        "core",
        "slab",
        "gros oeuvre",
        "gros œuvre",
        "estrutura",
        "estructura",
        "charpente",
        "timber",
        "clt",
        "glulam",
        "base build",
        "shell",
        "civil",
        "主体结构",
        "结构",
        "steel",
        "ruwbouw",
        "betonskelet",
        "hruba stavba",
        "zelezobeton",
        "żelbet",
        "konstrukcja",
        "szerkezet",
        "vasbeton",
        "alapozás",
        "σκυρόδεμ",
        "σκυροδέμ",
        "φέρων",
        "монолит",
        "моноліт",
        "каркас",
        "фундамент",
        "общестроительные",
        "beton armat",
        "radier",
        "stomme",
        "baerende",
        "bæren",
        "鉄骨",
        "躯体",
    ),
    "masonry": (
        "masonry",
        "mauerwerk",
        "maçonnerie",
        "maconnerie",
        "alvenaria",
        "albañiler",
        "albanileria",
        "vedações",
        "砌筑",
        "metselwerk",
        "zdivo",
        "falazat",
        "τοιχοποι",
        " кладк",
        "zidărie",
        "murowan",
    ),
    "envelope": (
        "facade",
        "fassade",
        "façade",
        "fachada",
        "envelope",
        "enveloppe",
        "envolvente",
        "curtain wall",
        "curtain-wall",
        "mur-rideau",
        "muro cortina",
        "window",
        "fenster",
        "glazing",
        "verglasung",
        "pfosten-riegel",
        "wdvs",
        "sonnenschutz",
        "cladding",
        "bardage",
        "esquadrias",
        "canceleria",
        "storefront",
        "幕墙",
        "外立面",
        "门窗",
        "gevel",
        "fasad",
        "elewacja",
        "homlokzat",
        "függönyfal",
        "κουφώμ",
        "фасад",
        "închideri",
        "tâmplărie",
        "stolarka okienna",
        "カーテンウォール",
        "外装",
    ),
    "roofing": (
        "roof",
        "roofing",
        "dakbedek",
        "tetősz",
        "střech",
        "dach",
        "toiture",
        "couverture",
        "étanchéité",
        "etancheite",
        "cubierta",
        "cobertura",
        "waterproofing",
        "abdichtung",
        "tak",
        "dak",
        "krov",
        "pokrycie dachu",
        "tető",
        "кровл",
        "покрівл",
        "acoperiș",
    ),
    "fitout": (
        "fit-out",
        "fitout",
        "fit out",
        "innenausbau",
        "ausbau",
        "finish",
        "trockenbau",
        "drywall",
        "partition",
        "cloison",
        "doublage",
        "ceiling",
        "plafond",
        "forro",
        "plafones",
        "floor",
        "boden",
        "estrich",
        "fliesen",
        "parkett",
        "maler",
        "türen",
        "door",
        "joinery",
        "millwork",
        "menuiseries",
        "revêtement",
        "revetement",
        "revestimento",
        "acabamento",
        "acabados",
        "finitions",
        "second oeuvre",
        "white space",
        "raised floor",
        "doppelboden",
        "akustikdecke",
        "gypse",
        "peinture",
        "pintura",
        "carrelage",
        "ladeneinrichtung",
        "interior",
        "shopfit",
        "精装修",
        "装修",
        "afbouw",
        "dokončovací",
        "wykończ",
        "επιχρίσμ",
        "отделк",
        "оздоблюв",
        "finisaje",
        "内装",
    ),
    "mechanical": (
        "mechanical",
        "hvac",
        "heizung",
        "lüftung",
        "sanitär",
        "hls",
        "tga",
        "cvc",
        "plomberie",
        "plumbing",
        "hidro",
        "hidráu",
        "hydraul",
        "mécanique",
        "climatiza",
        "aire acondicionado",
        "cooling",
        "kälte",
        "chiller",
        "wärme",
        "fernwärme",
        "fluides",
        "public health",
        "wet services",
        "medical gas",
        "process",
        "geothermie",
        "géothermie",
        "给排水",
        "暖通",
        "hkls",
        "lueftung",
        "sanitaer",
        "waerme",
        "vvs",
        "ventil",
        "fjernvarme",
        "fjaernvarme",
        "fjaerrvaaerme",
        "kjoeling",
        "koeling",
        "kyla",
        "werktuigbouw",
        "sanitair",
        "vytapeni",
        "vzt",
        "sanitar",
        "ogrzew",
        "kanaliz",
        "gépészet",
        "hőközpont",
        "légkezel",
        "ύδρευση",
        "αποχέτευση",
        "θέρμανση",
        "отоплен",
        "опален",
        "вентиляц",
        "водоснабж",
        "водопровід",
        "канализац",
        "каналізац",
        "termice",
        "空調",
        "衛生",
    ),
    "fire": (
        "fire",
        "sprinkler",
        "brandschutz",
        "incêndio",
        "incendio",
        "ssi",
        "suppression",
        "life safety",
        "sicherheitstechnik",
        "gicleurs",
        "消防",
        "brannalarm",
        "brandlarm",
        "brandalarm",
        "brandmeld",
        "brandveilig",
        "eps",
        "kebakaran",
        "incendiu",
        "消火",
    ),
    "electrical": (
        "electric",
        "elektro",
        "électric",
        "electricite",
        "elétric",
        "eléctric",
        "electrica",
        "starkstrom",
        "schwachstrom",
        "beleuchtung",
        "lighting",
        "éclairage",
        "power",
        "cfo",
        "cfa",
        "ms/ns",
        "glt",
        "telecom",
        "communications",
        "elv",
        "substation",
        "grid",
        "ladeinfrastruktur",
        "courant fort",
        "电气",
        "智能化",
        "elkraft",
        "elektri",
        "elektro",
        "elektry",
        "teletechnika",
        "erősáram",
        "ηλεκτρολογ",
        "электр",
        "електр",
        "слабкі струми",
        "electrice",
        "電気",
    ),
    "solar": ("photovolta", "solar", "pv"),
    "storage": ("bess", "battery energy", "battery storage", "battery container", "batteriespeicher", "energy storage"),
    "lifts": (
        "lift",
        "elevator",
        "aufzug",
        "ascenseur",
        "elevador",
        "escalator",
        "vertical transport",
        "fördertechnik",
        "电梯",
        "heiser",
        "hissar",
        "elevatorer",
        "liften",
        "vytahy",
        "dźwig",
        "felvonó",
        "ανελκυστ",
        "лифт",
        "ліфт",
        "ascensoare",
        "昇降機",
    ),
    "external": (
        "außenanlagen",
        "aussenanlagen",
        "exterieur",
        "extérieur",
        "landscap",
        "paving",
        "pavement",
        "pflaster",
        "begrünung",
        "verkehrsflächen",
        "vrd",
        "voirie",
        "réseaux",
        "paisagismo",
        "áreas externas",
        "site work",
        "sitework",
        "roads",
        "pavage",
        "sewer",
        "pipeline",
        "drainage",
        "entwässerung",
        "stormwater",
        "utilities",
        "plantation",
        "amenidades",
        "infrastructure",
        "园林",
        "室外",
        "external works",
        "external development",
        "aussenanlagen",
        "buitenruimte",
        "благоустр",
        "благоустрій",
    ),
}

# The order a description is read in when neither a code nor a bucket placed
# the position: narrow trades first, so "fire sprinkler mains" is fire.
_DESCRIPTION_ORDER: tuple[str, ...] = (
    "storage",
    "lifts",
    "fire",
    "solar",
    "piling",
    "earthworks",
    "roofing",
    "envelope",
    "masonry",
    "fitout",
    "mechanical",
    "electrical",
    "external",
    "structure",
    "prelims",
)

# A combined services package names every services trade, weakly, so a
# package that names one of them outright still wins that one.
_MEP_WORDS = (
    "mep",
    "m&e",
    "building services",
    "services",
    "instalaciones",
    "instalações",
    "instalacje",
    "instalații",
    "installaties",
    "инженерные системы",
    "інженерні системи",
    "ηλεκτρομηχανολογ",
    "tzb",
    "机电",
    "設備",
)
_MEP_TRADES = ("mechanical", "electrical", "fire", "lifts")

# What a package customarily carries when no package names it: the structure
# contractor the site set-up, the pit and the blockwork, the facade contractor
# the roof and the other way round, the electrician the PV.
_IMPLIED: dict[str, tuple[str, ...]] = {
    "structure": ("prelims", "earthworks", "piling", "masonry"),
    "envelope": ("roofing",),
    "roofing": ("envelope",),
    "electrical": ("solar",),
}

# A main contract takes whatever no trade package names.
_MAIN_CONTRACT_WORDS = (
    "main contract",
    "main building contract",
    "generalunternehmer",
    "design & build",
    "design and build",
    "precios unitarios",
    "main works contract",
    "general contract",
    "генеральний підряд",
    "κύρια σύμβαση",
)

#: Claim strength: the trade is named in the package name.
NAMED_IN_NAME = 2
#: Claim strength: the trade is named in the package description.
NAMED_IN_DESCRIPTION = 1
#: Claim strength: the package customarily carries the trade.
CUSTOMARY = 0


@dataclass(frozen=True)
class PackageClaim:
    """What one tender package promises to cover."""

    trades: dict[str, int] = field(default_factory=dict)
    din276_groups: tuple[str, ...] = ()
    main_contract: bool = False
    words: frozenset[str] = frozenset()


def _says(text: str, word: str) -> bool:
    # A short Latin word must be a whole word (plural allowed), or "tak"
    # would find "taking" and "eps" "steps". A longer one may sit inside a
    # compound, which is how German, Dutch and the Nordic languages write
    # trades ("Fussbodenheizung").
    if word.isascii() and len(word) < 5:
        return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?:s|es)?(?![a-z0-9])", text) is not None
    return word in text


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[\w-]{5,}", text.lower()))


def _named(claim: PackageClaim) -> int:
    """How many trades a package names outright; the narrower package wins a tie."""
    return sum(1 for strength in claim.trades.values() if strength > CUSTOMARY)


def _longest_prefix(table: dict[str, str], code: str) -> str | None:
    for length in range(len(code), 0, -1):
        hit = table.get(code[:length])
        if hit:
            return hit
    return None


def din276_digits(classification: dict | None) -> str:
    """The digits of a position's DIN 276 code, or ``""``."""
    return re.sub(r"\D", "", str((classification or {}).get("din276") or ""))


def position_trade(classification: dict | None, cwicr_ref: str | None, description: str) -> str:
    """Return the trade of one bill position.

    Args:
        classification: The position's classification map.
        cwicr_ref: The trade bucket the seeded build-up carries
            (``metadata["cwicr_ref"]``), if any.
        description: The position text.

    Returns:
        One of :data:`TRADES`; ``"prelims"`` when nothing places it.
    """
    cls = classification or {}
    text = f" {description} ".lower()
    # Storage is read from the words first: no classification standard has a
    # code of its own for a battery container, and it is its own package.
    if any(_says(text, w) for w in _WORDS["storage"]):
        return "storage"
    din = din276_digits(cls)
    if din:
        specific = din.rstrip("0") or din
        hit = _longest_prefix(_DIN276, specific)
        if hit and specific not in _DIN276_HEADINGS:
            return hit
    masterformat = str(cls.get("masterformat") or "").strip()
    if re.match(r"^\d\d", masterformat):
        hit = _longest_prefix(_MASTERFORMAT, masterformat)
        if hit:
            return hit
    bucket = (cwicr_ref or "").split("-")[1] if (cwicr_ref or "").count("-") >= 1 else ""
    if bucket in _BUCKET_TRADE:
        return _BUCKET_TRADE[bucket]
    # NRM is read after the bucket: several packs number their own elements
    # under the NRM key, so the bucket is the safer reading where there is one.
    nrm = str(cls.get("nrm") or "").strip()
    if re.match(r"^\d", nrm):
        parts = nrm.split(".")
        for count in range(len(parts), 0, -1):
            hit = _NRM.get(".".join(parts[:count]))
            if hit:
                return hit
    for trade in _DESCRIPTION_ORDER:
        if any(_says(text, w) for w in _WORDS[trade]):
            return trade
    return "prelims"


def package_claim(name: str, description: str) -> PackageClaim:
    """Read what a tender package promises from its name and description."""
    head, body = f" {name} ".lower(), f" {description} ".lower()
    trades: dict[str, int] = {}
    for trade, words in _WORDS.items():
        if any(_says(head, w) for w in words):
            trades[trade] = NAMED_IN_NAME
        elif any(_says(body, w) for w in words):
            trades[trade] = NAMED_IN_DESCRIPTION
    for trade, carried in _IMPLIED.items():
        if trade in trades:
            for other in carried:
                trades.setdefault(other, CUSTOMARY)
    if any(_says(head + body, w) for w in _MEP_WORDS):
        for trade in _MEP_TRADES:
            trades.setdefault(trade, NAMED_IN_DESCRIPTION)
    groups: list[str] = []
    for match in re.finditer(r"KG\s*(\d{3}(?:\s*[+,/]\s*\d{3})*)", f"{name} {description}"):
        groups.extend(code.rstrip("0") or code for code in re.findall(r"\d{3}", match.group(1)))
    return PackageClaim(
        trades=trades,
        din276_groups=tuple(groups),
        main_contract=any(_says(head + body, w) for w in _MAIN_CONTRACT_WORDS),
        words=_tokens(f"{name} {description}"),
    )


def assign_package_scopes(
    packages: list[tuple[str, str]],
    positions: list[tuple[str, str, str]],
) -> list[list[int]]:
    """Assign each position to the package whose trade it is.

    Args:
        packages: ``(name, description)`` of each package, in order.
        positions: ``(trade, din276_digits, description)`` of each priced
            position, as :func:`position_trade` and :func:`din276_digits`
            give them.

    Returns:
        One list of position indexes per package. A position no package
        covers is in none of them.
    """
    claims = [package_claim(name, description) for name, description in packages]
    coded = any(claim.din276_groups for claim in claims)
    main = [i for i, claim in enumerate(claims) if claim.main_contract]
    scopes: list[list[int]] = [[] for _ in packages]
    for index, (trade, din, description) in enumerate(positions):
        target: int | None = None
        if coded:
            # A pack that tenders by cost group covers those groups and
            # nothing else; reading its words as well would pull the rest of
            # the bill into packages the dossier never tendered.
            owners = [
                i for i, claim in enumerate(claims) if din and any(din.startswith(g) for g in claim.din276_groups)
            ]
            target = owners[0] if owners else None
        else:
            words = _tokens(description)
            named = [i for i, claim in enumerate(claims) if claim.trades.get(trade, CUSTOMARY) > CUSTOMARY]
            customary = [i for i, claim in enumerate(claims) if claim.trades.get(trade) == CUSTOMARY]
            if named:
                target = min(
                    named,
                    key=lambda i: (-claims[i].trades[trade], -len(words & claims[i].words), _named(claims[i]), i),
                )
            elif main:
                target = main[0]
            elif customary:
                target = min(customary, key=lambda i: (-len(words & claims[i].words), _named(claims[i]), i))
        if target is not None:
            scopes[target].append(index)
    return scopes


# ── Seeded tender timeline ────────────────────────────────────────────

#: Statuses of a package that is still taking bids.
OPEN_STATUSES = frozenset({"draft", "issued", "collecting"})

#: The invited firm that has not quoted yet on an open package. Fictional,
#: on a reserved domain, and the same in every pack.
PENDING_INVITEE = ("Calderwyn Contracting", "tenders@calderwyn.example")


def seeded_package_statuses(statuses: list[str], has_bids: list[bool]) -> list[str]:
    """Make each package's status agree with the bids seeded into it.

    A package holding submitted bids has been sent out and is collecting,
    whatever stage the pack wrote. A pack whose packages are all closed gets
    its last evaluating package reopened, so every pack tells the open part
    of the story as well: a tender still out, with a firm yet to quote.
    """
    result = [
        "collecting" if status in {"draft", "issued"} and bids else status
        for status, bids in zip(statuses, has_bids, strict=True)
    ]
    if not any(status in OPEN_STATUSES for status in result):
        evaluating = [i for i, status in enumerate(result) if status == "evaluating"]
        if evaluating:
            result[evaluating[-1]] = "collecting"
    return result


def seeded_deadlines(statuses: list[str], today: date) -> list[date]:
    """Date each package's deadline relative to the install day.

    Open packages close three weeks out and a week apart; closed ones closed
    two weeks ago and earlier, in pack order, so the first package tendered
    is also the first one closed.
    """
    closed = [i for i, status in enumerate(statuses) if status not in OPEN_STATUSES]
    deadlines: list[date] = []
    open_seen = 0
    for index, status in enumerate(statuses):
        if status in OPEN_STATUSES:
            deadlines.append(today + timedelta(days=21 + 7 * open_seen))
            open_seen += 1
        else:
            later = len(closed) - 1 - closed.index(index)
            deadlines.append(today - timedelta(days=14 + 7 * later))
    return deadlines


def seeded_issued_at(status: str, deadline: date, today: date) -> datetime:
    """When the package went out: four weeks before a past deadline, two weeks ago for an open one."""
    day = today - timedelta(days=14) if status in OPEN_STATUSES else deadline - timedelta(days=28)
    return datetime.combine(day, time(9, 0), tzinfo=UTC)


def seeded_submitted_at(status: str, deadline: date, today: date, bidder_index: int) -> datetime:
    """When one bidder submitted: before the deadline, and never after the install day."""
    back = timedelta(days=1 + min(bidder_index, 9))
    day = today - back if status in OPEN_STATUSES else deadline - back
    return datetime.combine(min(day, today), time(10 + bidder_index % 6, 0), tzinfo=UTC)


def seeded_recipients(
    bidders: list[tuple[str, str]],
    *,
    sent_at: datetime,
    pending_invitee: tuple[str, str] | None,
) -> list[dict]:
    """The package's invitation list, in the shape the tendering module stores.

    Every bidder was invited, so each one is a recipient whose invitation was
    sent. An open package also invited one firm that has not quoted yet.
    """
    invited = list(bidders)
    if pending_invitee is not None and all(email != pending_invitee[1] for _name, email in invited):
        invited.append(pending_invitee)
    stamp = sent_at.isoformat()
    return [
        {
            "id": str(uuid.uuid4()),
            "company_name": name,
            "email": email,
            "subcontractor_id": None,
            "status": "sent",
            "sent_at": stamp,
            "last_error": None,
            "created_at": stamp,
        }
        for name, email in invited
    ]
