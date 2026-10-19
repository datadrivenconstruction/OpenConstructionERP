# KSeF fixtures

Official files published by the Polish Ministry of Finance, kept unedited.

* `fa3/schemat_FA(3)_v1-0E.xsd` is the FA(3) logical structure, namespace
  `http://crd.gov.pl/wzor/2025/06/25/13775/`. It is byte-identical to
  https://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd and to
  `faktury/schemy/FA/schemat_FA(3)_v1-0E.xsd` in https://github.com/CIRFMF/ksef-docs.
* `fa3/bazowe/*.xsd` are the shared type schemas it imports. They are imported by their
  `http://crd.gov.pl/...` URLs; the tests resolve those URLs to these files, so validation never
  touches the network.
* `upo/upo-faktura-kontekst-id-nip.xml` is the UPO example for one invoice (UPO schema v4-3).

Read 2026-10-19. Licence: MIT, copyright 2025 Ministerstwo Finansow, text in `LICENSE.txt`.
