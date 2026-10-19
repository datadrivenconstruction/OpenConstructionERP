# ETA SDK sample documents

Copied from the Egyptian Tax Authority e-invoicing SDK, https://sdk.invoicing.eta.gov.eg/files/, read
2026-10-19. They are ETA's own artefacts and are kept unedited so the tests can prove the platform agrees with
ETA byte for byte.

| File | Source | What it is |
|---|---|---|
| `one-doc.json` | https://sdk.invoicing.eta.gov.eg/files/one-doc.json | An unsigned document, `documentTypeVersion` 0.9, every tax type on each line |
| `one-doc-serialized.json.txt` | https://sdk.invoicing.eta.gov.eg/files/one-doc-serialized.json.txt | ETA's canonical serialization of `one-doc.json` |
| `one-doc-I.json` | https://sdk.invoicing.eta.gov.eg/files/one-doc-I.json | The same document with an issuer CAdES-BES signature |

The only change is the UTF-8 byte order mark at the start of `one-doc-I.json`, which was removed. The canonical
form ignores whitespace and line endings, so a checkout with CRLF line endings tests the same thing.

Used by `tests/unit/test_einvoice_eta_sdk_samples.py`, `test_einvoice_eta_documents.py` and
`test_einvoice_eta_api.py`. The specification is `docs/design/egypt/eta.md`.
