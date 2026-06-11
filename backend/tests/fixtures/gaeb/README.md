# GAEB test fixtures

## bvbs_pruefdatei_3.3_x84.x84

Official BVBS/GAEB Pruefdatei (conformance test file) for GAEB DA XML 3.3,
exchange phase DP 84 (X84 Angebotsabgabe / priced bid submission), namespace
`http://www.gaeb.de/GAEB_DA_XML/DA84/3.3`, 5,546 bytes.

These Pruefdateien are published by GAEB/BVBS for implementers to verify their
own readers and writers against. This copy was taken from the test fixtures of
the MIT-licensed open-source parser `meindonut/gaeb-parser` (pinned commit
dc31d83), file
`tests/official_tests_gaeb_da_xml_3_3/bauausfuehrung/BVBS_Pruefdatei GAEB DA XML 3.3 - Bauausfuehrung - V 11 06 2021.x84`.

Used by `tests/unit/test_gaeb_x84_import_money.py` to pin that the importer
preserves every cent of an X84 bid (the file declares a 2,000,000.00 EUR LV).
