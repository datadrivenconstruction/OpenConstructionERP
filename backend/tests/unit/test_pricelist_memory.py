"""A large price list is read as a stream: memory stays flat as the file grows.

The real lists run to 125 MB of XML (Lombardia 2026) and the core server has
3 GB. The test writes a Toscana-layout file of about 25 MB to a temporary file,
reads it end to end through the same path the endpoint uses, and holds the
Python heap peak to a small fraction of the file. The file is deleted after.
"""

from __future__ import annotations

import tempfile
import tracemalloc
from pathlib import Path

import pytest

from app.modules.costs.pricelists.service import build_preview, plan_upload

_ARTICLES = 16_000

_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<EASY:Prezzario xmlns:EASY="https://prezzariollpp.regione.toscana.it/prezzario.xsd">\n'
    '<EASY:intestazione autore="Regione Toscana"><EASY:dettaglio anno="2025" area="Provincia di Prova"/>'
    '<EASY:copyright tipo="CC BY 3.0"/></EASY:intestazione>\n<EASY:Contenuto>\n'
)
_ARTICLE = (
    '<EASY:Articolo cam="0" codice="TOS25_01.A03.{n:03d}.{m:03d}">'
    "<EASY:livello1><![CDATA[NUOVE COSTRUZIONI EDILI.]]></EASY:livello1>"
    "<EASY:livello2><![CDATA[DEMOLIZIONE. {pad}]]></EASY:livello2>"
    "<EASY:livello3><![CDATA[TOTALE O PARZIALE DI EDIFICI]]></EASY:livello3>"
    "<EASY:livello4><![CDATA[voce {n}.{m}]]></EASY:livello4>"
    "<EASY:um><![CDATA[m³]]></EASY:um><EASY:prezzo>13.63017</EASY:prezzo>"
    "<EASY:Analisi>"
    '<EASY:vocedettaglio codice="TOS25_RU.M10.001.002" tipo="TOS25_RU" udm="ora" quantita="0.1" '
    'prezzo="38.00000" importo="3.80000"><EASY:descrizione><![CDATA[Operaio qualificato]]></EASY:descrizione>'
    "</EASY:vocedettaglio>"
    '<EASY:vocedettaglio codice="TOS25_AT.N01.001.205" tipo="TOS25_AT" udm="ora" quantita="0.2" '
    'prezzo="32.17180" importo="6.43436"><EASY:descrizione><![CDATA[Escavatore]]></EASY:descrizione>'
    "</EASY:vocedettaglio>"
    '<EASY:totaleparziale valore="10.23436"/><EASY:spesegenerali percentuale="16" valore="1.63750"/>'
    '<EASY:utileimpresa percentuale="10" valore="1.17219"/>'
    '<EASY:incidenzamanodopera percentuale="27.88" valore="3.80000"/>'
    "</EASY:Analisi></EASY:Articolo>\n"
)


@pytest.mark.slow
def test_a_large_list_is_previewed_in_bounded_memory() -> None:
    pad = "Eseguita con qualsiasi mezzo, compresi gli oneri per le opere provvisionali. " * 6
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Grande-2025.xml"
        with path.open("w", encoding="utf-8") as out:
            out.write(_HEAD)
            for i in range(_ARTICLES):
                out.write(_ARTICLE.format(n=i // 1000, m=i % 1000, pad=pad))
            out.write("</EASY:Contenuto></EASY:Prezzario>\n")
        size = path.stat().st_size
        assert size > 20 * 1024 * 1024

        tracemalloc.start()
        try:
            with path.open("rb") as stream:
                preview = build_preview(plan_upload(stream, path.name))
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert preview["counts"]["importable"] == _ARTICLES
    assert preview["counts"]["with_analysis"] == _ARTICLES
    # Measured at about 2 MB; a reader that kept the tree would hold several
    # times the file. A tenth of the file leaves room without hiding that.
    assert peak < size / 10, f"peak {peak / 1e6:.1f} MB for a {size / 1e6:.1f} MB file"
