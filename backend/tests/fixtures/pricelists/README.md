# Regional price-list fixtures

Excerpts of the price lists Italian regions publish, cut to a handful of rows
for the reader tests (`tests/unit/test_pricelist_adapters.py`) and otherwise
unchanged. Each file names its source in its first line or comment.

| File | Publisher, list, edition | Licence as found |
|---|---|---|
| `toscana_firenze_2025.xml` | Regione Toscana, Prezzario dei Lavori Pubblici della Toscana 2025, Provincia di Firenze, XML | CC BY 3.0, stated in the file header |
| `veneto_2026.xml` | Regione del Veneto, Prezzario regionale dei lavori pubblici 2026, XML | none stated in the file |
| `lombardia_2026.xml` | Regione Lombardia, Prezzario regionale delle opere pubbliche 2026 (edizione 1), XML | none stated in the file |
| `lombardia_2026_legacy.xml` | the same list in its previous layout, from the same archive | none stated in the file |
| `lazio_2023_parte_a.csv` | Regione Lazio, Tariffa dei prezzi 2023, part A (Windows-1252) | not checked |
| `lazio_2023_parte_e.csv` | Regione Lazio, Tariffa dei prezzi 2023, part E (UTF-8) | not checked |
| `umbria_2025.json.cp1252` | Regione Umbria, Elenco regionale dei prezzi 2025, JSON (Windows-1252, original bytes preserved; tests upload it as `.json`) | CC BY 4.0, open-data catalogue record |
| `campania_2024.csv` | Regione Campania, Prezzario dei lavori pubblici 2024 | CC BY 4.0, open-data catalogue record |
| `puglia_2026.csv` | Regione Puglia, Prezzario regionale 2026 | CC BY 4.0, open-data catalogue record |
| `piemonte_2023.csv` | Regione Piemonte, Prezzario regionale 2023 | CC BY 4.0, open-data catalogue record |

The SIX test file is synthetic, built in the test to the published schema; no
regional list in that format was available.
