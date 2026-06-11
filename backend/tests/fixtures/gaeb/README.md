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
preserves every cent of an X84 bid (the file declares a 2,000,000.00 EUR LV),
and by `tests/unit/test_gaeb_export_xsd.py` to pin the XSD oracle.

## xsd/

Official GAEB DA XML 3.2 (2012-01) schema set published by the Gemeinsamer
Ausschuss Elektronik im Bauwesen (GAEB) for implementers:

- `GAEB_DA_XML_00_3.2_2012-01_Lib.xsd` - shared library types.
- `GAEB_DA_XML_83_3.2_2012-01.xsd` - X83 (Angebotsaufforderung).
- `GAEB_DA_XML_84_3.2_2012-01.xsd` - X84 (Angebotsabgabe).

GAEB does not publish the 3.3 XSD as a free download, but the X83/X84 BoQ
element model is the same in 3.3. `tests/unit/test_gaeb_export_xsd.py` adapts
this 3.2 schema into a faithful 3.3 oracle (rewrites the `DA8x/3.2` target
namespace to `DA8x/3.3` and widens the Version/VersDate facets), then pins the
oracle by first validating the official BVBS 3.3 Pruefdatei against it. The
exporter's output is validated against the result. These are open schema
definitions for a public data-exchange standard.
