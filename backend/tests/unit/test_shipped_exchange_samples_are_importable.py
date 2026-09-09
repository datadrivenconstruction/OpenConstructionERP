# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The sample budgets the regional exchange screens offer must import as budgets.

Every country screen under ``/regional-exchange`` may name a ``sampleFile``, and
the page renders it as "download a sample file to try it". That file is the first
and often the only thing a visitor runs through the importer, so it is the one
file in the tree whose failure reads as "this product cannot import my format".

On 9 September 2026 the Spanish one failed twice over and neither half was
visible from inside the product.

The proxy would not serve it. ``/templates/es-pbc-sample.bc3`` came back 200 with
``text/html`` and 6781 bytes of ``index.html``, because ``.bc3`` was not in the
set of suffixes the SPA fallback serves from the dist root. The link handed the
visitor an HTML page under a ``.bc3`` name, and the page's own client-side parser
then read that HTML and announced three positions found in it.

And the file itself was written to a record layout nothing else in the tree uses.
A FIEBDC ``~C`` record carries the price at field 3 and the type at field 6; the
sample carried a currency at 3, a date at 5 and its quantities in ``~D`` triplets
rather than in ``~M`` measurements. It parsed without a single error and imported
nine rows: three chapters as priced work items, five partidas with no rate and no
quantity, and the budget header as a position priced at 26,052,026, which is the
file's date read as money.

So this module asks the two questions that separate a sample that works from a
sample that merely exists. Can the origin hand the bytes over, and does an
importer turn them into a budget with money in it. Both fail on what shipped.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.cli_static import SERVED_ROOT_EXTENSIONS
from app.modules.boq.importers import REGISTERED_IMPORTERS

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DIR = REPO_ROOT / "frontend" / "public"
TEMPLATES_DIR = PUBLIC_DIR / "templates"
REGISTRY_TS = REPO_ROOT / "frontend" / "src" / "modules" / "regional-exchange" / "regionalRegistry.ts"

#: ``sampleFile: '/templates/nrm-sample.csv',`` in the country template table.
_SAMPLE_FILE_RE = re.compile(r"""sampleFile:\s*(['"])(?P<path>/[^'"]+)\1""")


def _declared_sample_paths() -> list[str]:
    """Public URLs the regional exchange screens offer for download."""
    source = REGISTRY_TS.read_text(encoding="utf-8")
    return [m.group("path") for m in _SAMPLE_FILE_RE.finditer(source)]


def _importer_for(data: bytes, name: str):  # noqa: ANN202 - the registry's own union
    """The importer that claims this upload, the way the dispatcher picks one."""
    return next((imp for imp in REGISTERED_IMPORTERS if imp.detect(data[:4096], name)), None)


def test_the_registry_names_at_least_one_sample_per_shipped_format_family():
    """Guard the regex, not the product.

    Every assertion below is driven by what this finds, so a pattern that
    silently matched nothing would turn the whole module green while measuring
    an empty set.
    """
    paths = _declared_sample_paths()
    assert len(paths) >= 4, f"only {len(paths)} sampleFile entries found in {REGISTRY_TS.name}"
    assert len({Path(p).suffix.lower() for p in paths}) >= 2, (
        "every declared sample has the same extension, which is not what the registry carries; "
        "the pattern is probably matching one line and repeating it"
    )


@pytest.mark.parametrize("public_path", _declared_sample_paths())
def test_a_declared_sample_file_is_actually_in_the_bundle(public_path: str):
    """A path in the registry is a promise the build has to keep."""
    on_disk = PUBLIC_DIR / public_path.lstrip("/")
    assert on_disk.is_file(), f"{public_path} is offered for download and is not in frontend/public"


@pytest.mark.parametrize("sample", sorted(TEMPLATES_DIR.iterdir()) if TEMPLATES_DIR.is_dir() else [])
def test_the_origin_will_serve_a_file_it_offers_for_download(sample: Path):
    """The whole point of ``/templates`` is to be fetched.

    Asked over the directory rather than over the registry's four entries,
    because the failure is a property of the suffix and the next sample added
    there will be found by this test before anyone clicks the link.
    """
    assert sample.suffix.lower() in SERVED_ROOT_EXTENSIONS, (
        f"{sample.name} is published for download and its suffix is not one the SPA fallback "
        f"serves, so the request comes back 200 carrying index.html under that name"
    )


@pytest.mark.parametrize("public_path", _declared_sample_paths())
def test_a_sample_imports_as_a_budget_with_money_in_it(public_path: str):
    """The question a visitor is really asking when they click the link.

    Quantity and rate together, on every work item, because either one alone
    passes on the file that broke: its rows had descriptions, codes and units,
    and an estimate with no numbers is not an estimate.
    """
    on_disk = PUBLIC_DIR / public_path.lstrip("/")
    data = on_disk.read_bytes()

    importer = _importer_for(data, on_disk.name)
    assert importer is not None, f"no registered importer claims {on_disk.name}"

    result = asyncio.run(importer.parse(data))
    items = [p for p in result.positions if not p.is_section]
    assert items, f"{on_disk.name} produced {len(result.positions)} rows and not one work item"
    assert not result.errors, f"{on_disk.name} imported with errors: {result.errors}"

    unpriced = [p.ordinal for p in items if not p.unit_rate or p.unit_rate <= 0]
    unmeasured = [p.ordinal for p in items if not p.quantity or p.quantity <= 0]
    assert not unpriced, f"{on_disk.name}: {len(unpriced)} of {len(items)} items carry no rate: {unpriced}"
    assert not unmeasured, f"{on_disk.name}: {len(unmeasured)} of {len(items)} items carry no quantity: {unmeasured}"


def test_the_spanish_sample_reads_back_the_figures_it_was_written_with():
    """One sample checked by value, so the shape test above cannot pass on noise.

    The rate that broke the old file was 26,052,026, a date, and it is a positive
    number: a test that only asks "is there a rate" would have called it priced.
    """
    data = (PUBLIC_DIR / "templates" / "es-pbc-sample.bc3").read_bytes()
    importer = _importer_for(data, "es-pbc-sample.bc3")
    assert importer is not None
    result = asyncio.run(importer.parse(data))

    assert result.currency == "EUR"
    by_code = {p.ordinal: p for p in result.positions}
    assert {"01#", "02#", "03#"} <= set(by_code), "the three capitulos did not come back as sections"
    assert all(by_code[c].is_section for c in ("01#", "02#", "03#"))

    concrete = by_code["02.01"]
    assert concrete.unit == "m3"
    assert concrete.quantity == pytest.approx(180.0)
    assert concrete.unit_rate == pytest.approx(142.50)

    items = [p for p in result.positions if not p.is_section]
    assert sum(p.quantity * p.unit_rate for p in items) == pytest.approx(75_483.00)
