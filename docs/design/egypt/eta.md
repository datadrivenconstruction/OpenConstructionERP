# Egypt: ETA e-invoicing (clearance adapter)

Status: implemented on `wip/eg-eta-20261019`, offline-tested. Not yet run against the ETA pre-production
environment, which needs the partner's taxpayer credentials and an eSeal (see "What remains for a live pilot").

## Scope

Egyptian Tax Authority (ETA) e-invoicing for B2B invoices, credit notes and debit notes, including the export
variants. The legal basis is Unified Tax Procedures Law 206/2020, Art. 35, with the rollout by ETA decisions
(188/2020 and following). The ETA model is clearance: every document is submitted, validated by ETA and receives a
26 character UUID; a document ETA marks `invalid` is not an invoice.

In scope:

1. An `EG` row in the clearance regime registry (`einvoice_clearance/regimes.py`), with sourced metadata.
2. The official ETA code tables shipped as data, unedited: tax types T1-T12, non-taxable types T13-T20, the 56 tax
   subtypes (V001-V010, Tbl01-02, W001-W016, ST01-04, ...), unit types and activity codes.
3. A document builder from the platform's finance invoice to an ETA v1.0 JSON document, with the SDK calculation
   rules, and the canonical serialization that ETA hashes for signing.
4. Pre-submit validation as validation rules in the existing `einvoice_clearance` rule set.
5. A pluggable signer for the CAdES-BES signature, with a test signer, a PKCS#11 signer and an external signing
   service hook.
6. An ETA API client (OAuth2 client credentials, submit, get submission, get document details, get document
   type, cancel, reject) behind the existing `ClearanceAdapter` interface, never called by a test.

Out of scope here: the B2C e-receipt system (a separate ETA platform with its own document family), the EGS item
code registration API (`/api/v1.0/codetypes/requests/codes`, master data the partner registers once), the inbound
side (receiving and rejecting documents other taxpayers issued to us), and the callback endpoint
(`PUT /notifications/documents`, the push alternative to polling).

## Architecture decisions

**D1. The ETA client lives in its own module, `einvoice_eta`, not in `einvoice_clearance`.** The clearance module
promises in its docstring that no network calls live in it and that a real government client registers itself
from its own package. `einvoice_eta` is that package: a plugin with a manifest that depends on
`oe_einvoice_clearance` and, on startup, registers into the clearance module's existing registries (the adapter
registry, the validation rule set, and a new payload builder registry). It adds no tables and no router. Removing
the folder removes Egypt without touching the clearance module.

**D2. No new dependency.** HTTP goes through `httpx` and certificate handling through `cryptography`, both already
core dependencies (`backend/pyproject.toml`). The CAdES-BES structure is assembled with a small DER encoder in the
module (about 150 lines) rather than adding `asn1crypto` or a CMS library, because `cryptography`'s PKCS#7 builder
cannot add the `signingCertificateV2` attribute that CAdES-BES requires and cannot sign on a token. The DER output
is pinned byte for byte to the signed sample ETA publishes. PKCS#11 needs `python-pkcs11`, which is imported
lazily and only on a machine that configures a PKCS#11 signer; it is not a dependency of the platform.

**D3. Acceptance is not clearance.** ETA answers a submission with HTTP 202 and a UUID before it has validated
the document; `valid` or `invalid` arrives later. The adapter interface gains an additive `pending` flag on
`SubmissionOutcome`. A pending answer keeps the document in `submitted`, stores the ETA UUID as its authority
identifier, and records the long id in the trail. A new optional adapter capability, `poll`, and a new service
call and endpoint, `refresh`, read the outcome later: `valid` moves the document to `cleared`, `invalid` to
`rejected` with ETA's validation errors as the rejection message. Adapters without `poll` behave exactly as
before. On submit the adapter asks Get Submission a few times (`poll_attempts` x `poll_interval_seconds`, at
most 10 x 30 s, default 3 x 2 s) so a quick verdict lands in one step; `refresh` reads Get Document Details for
the one document, which also carries the failing validation steps.

**D4. The cancellation window is read from ETA, not shipped.** ETA states the window is per document type and
returned by Get Document Type in its workflow parameters; the commonly quoted figures (7 days to cancel, 3 days
to reject) are UNCONFIRMED. The registry gets an additive cancellation basis, `read_from_authority`, which makes a
row cancellable without a day count; the `cancellation_allowed` rule still requires a reason and leaves the window
to the adapter. The adapter reads the workflow parameter, refuses locally with `OperationPeriodOver` when it can
see the window has closed, and otherwise lets ETA decide. An accepted cancellation is a request: the SDK lets
the receiver decline it on the portal within ETA's window, so the success message says so rather than calling
the invoice withdrawn.

**D5. Credentials are never stored.** The profile stores the names of the environment variables that hold the
client id and secret (`client_id_env`, `client_secret_env`), never the values, matching the existing rule that a
profile carries no credential. The eSeal private key stays on the token or HSM; the PKCS#11 PIN is read from an
environment variable named in the settings.

**D6. Environment base URLs default from the published hosts.** The SDK FAQ (/faq/, read 2026-10-19) lists the
hosts of both environments: pre-production `id.preprod.eta.gov.eg` and `api.preprod.invoicing.eta.gov.eg`,
production `id.eta.gov.eg` and `api.invoicing.eta.gov.eg`, plus the portal and profile hosts. They live once, in the
regime row's `extra.environments` with their source, and a registration that names only `environment` gets them.
A registration may still name its own base URLs (a proxy, or hosts ETA changes later); a plain `http` URL is
refused. The profile's `sandbox` flag must agree with the environment (`preprod` with sandbox on, `prod` with
sandbox off); a mismatch is refused.

**D7. The adapter signs exactly the stored document.** The clearance contract says an adapter sends the stored
bytes and does not re-serialise them. The ETA submission body is `{"documents":[ ... ]}`, so the adapter embeds
the stored document text verbatim and inserts the `signatures` member before the document's closing brace. The
canonical serialization ignores formatting, so the signature stays valid for the stored text. A payload that
already carries `signatures` (signed upstream by the customer's own tool) is sent unchanged.

**D8. Duplicate protection.** ETA rejects an identical request body from the same taxpayer within 10 minutes with
`422 DuplicateSubmission` and a `Retry-After` header. The adapter treats that as "ETA may already hold this
document": it raises a transport-class error, which leaves the document `submitted` with an unknown outcome, the
same safe state the module already uses for a timeout. The operator then refreshes or resolves by hand. Locally,
the existing `payload_not_reused` rule already stops a second document with the same payload hash under one
registration.

**D9. Rounding.** The SDK allows 5 decimal places on amounts and checks the line and document equations. The
builder computes every amount with `Decimal` and rounds to 5 places, half up. The checker compares a supplied
amount with the recomputed one at the supplied amount's own precision and allows one unit in its last place,
because the SDK publishes no tolerance and its own sample is rounded to 2 places. This tolerance is a decision,
recorded here, not an ETA fact.

**D10. String values in the canonical form.** The SDK says JSON values are taken "as they are in the input". The
serializer uses the decoded string value and the literal text of numbers (`947.00` stays `947.00`). How ETA treats
an escaped quote or backslash inside a JSON string is not specified, so the advisory rule warns when a text value
contains `"` or `\`.

## Data and sources

All read on 2026-10-19 from https://sdk.invoicing.eta.gov.eg/ (the official ETA SDK).

| Fact | Where it is encoded | Source |
|---|---|---|
| Document types `i`, `c`, `d`, `ei`, `ec`, `ed` (`ii` import invoice exists, not built) | `einvoice_eta/codes.py` | /einvoicingapi/09-get-submission/ (typeName), /documents/invoice-v1-0/ |
| `documentTypeVersion` "1.0" | builder | /documents/invoice-v1-0/ |
| Party types B, P, F; issuer `branchID` mandatory for B; receiver and issuer differ | checks | /documents/invoice-v1-0/ |
| Tax types T1-T20, 56 subtypes with parent | `einvoice_eta/data/*.json` verbatim | /codes/tax-types/ (TaxTypes.json, NonTaxableTaxTypes.json, TaxSubtypes.json) |
| Unit types (144), activity codes (435) | `einvoice_eta/data/*.json` verbatim | /codes/unit-types/, /codes/activity-types/ |
| Line and document equations | `einvoice_eta/calculation.py` | /document-validation-rules/ |
| T3 and T6 rate must be 0 | checks | /document-validation-rules/ |
| Canonical serialization | `einvoice_eta/serialization.py` | /document-serialization-approach/ |
| CAdES-BES, SHA-256, signed attributes | `einvoice_eta/signing.py` | /signature-creation/, files/parsed-cades-bes.txt |
| OAuth2 client credentials on `/connect/token`, token 1 hour, cache it | `einvoice_eta/client.py` | /api/01-login-as-taxpayer-system/, /integrationpractices/ |
| Submit, 202, `DuplicateSubmission` 422 within 10 min | client, adapter | /einvoicingapi/01-submit-documents/ |
| Get Submission statuses, Get Document Details validation steps | client, adapter | /einvoicingapi/09-get-submission/, /einvoicingapi/11-get-document-details/ |
| Cancel via `PUT /api/v1.0/documents/state/{uuid}/state`, window from workflow parameters | client, adapter | /einvoicingapi/02-cancel-document/, /api/03-get-document-type/ |
| Pre-production and production hosts | regime row `extra.environments`, adapter default | /faq/ |
| `ec` and `ed` for export credit and debit notes | codes | /documents/export-credit-note-v1-0/, /documents/export-debit-note-v1-0/ |

The signature JSON member is `signatureType` and `value`, as in the SDK's signed sample `files/one-doc-I.json`;
the invoice page's table calls the first member `type`. The sample is the artefact ETA's own validator accepted,
so it wins.

### UNCONFIRMED, shipped as review data or left out

| Item | Treatment |
|---|---|
| Cancellation and rejection window length | Not shipped; read from Get Document Type at runtime (D4) |
| Person receiver ID threshold | Date-effective rows in `codes.PERSON_ID_THRESHOLDS`, both `needs_expert_review`: EGP 50,000 until 2024-07-31, EGP 25,000 from 2024-08-01 (head of ETA quoted in the press, https://hapijournal.com/2024/05/07/; no decree text reached; the SDK says only "threshold limit defined"). The advisory rule warns when a `P` receiver without id reaches the figure of the issue date; it never refuses |
| Maximum age of `dateTimeIssued` and the same-day submission deadline | Not enforced; the SDK confirms only "cannot be in future", which is enforced |
| EGS code format | Only the documented prefix `EG-` (GS1 Egypt, https://gs1eg.org/en/tools/eta-free-egs/) is checked, as a warning; the rest of the layout is described inconsistently and is not checked |
| Mapping of the platform's VAT categories to V-subtypes | Shipped as a small table flagged `needs_expert_review`; the builder only maps a standard rated line to T1/V009 by itself and asks for an explicit subtype otherwise |
| Platform unit to ETA unit map | Shipped as a table flagged `needs_expert_review`; note `KG` in ETA's table is a keg, kilogram is `KGM` |

## Profile settings

Stored in `EInvoiceProfile.settings["eta"]` (JSON, no migration):

```json
{
  "environment": "preprod",
  "identity_base_url": "(optional, defaults from environment)",
  "api_base_url": "(optional, defaults from environment)",
  "client_id_env": "OE_ETA_CLIENT_ID",
  "client_secret_env": "OE_ETA_CLIENT_SECRET",
  "on_behalf_of": "",
  "activity_code": "4100",
  "issuer": {"name": "...", "address": {"branchID": "0", "country": "EG", "governate": "Cairo",
             "regionCity": "Nasr City", "street": "...", "buildingNumber": "..."}},
  "default_item": {"itemType": "EGS", "itemCode": "EG-123456789-1001", "unitType": "C62"},
  "signer": {"kind": "pkcs11", "library": "C:/.../eps2003csp11.dll", "token_label": "...",
             "key_label": "...", "certificate_label": "...", "pin_env": "OE_ETA_TOKEN_PIN"},
  "poll_attempts": 3,
  "poll_interval_seconds": 2
}
```

`tax_registration_id` on the profile is the issuer RIN and must equal `issuer.id` in every document.

The RIN format itself is not checked here. It belongs to the shared party identifier package
(`app.core.party_identifiers`, scheme `rin` for EG), which the checks call as `check("EG", "rin", value)`
for the issuer and a B receiver. An invalid result is an error in `eta_parties`, or a warning in `eta_advisory`
while the shared check marks its rule `needs_expert_review`; where the package or the scheme
is not installed the check returns nothing and `eta_advisory` says the format was not checked.

Signer kinds: `pkcs11` (USB token or HSM through its PKCS#11 library), `external_http` (a signing service on the
machine the token is plugged into; the platform POSTs `{"canonical_base64", "sha256_hex"}` and expects
`{"signature": "<base64 CAdES-BES>"}`), `presigned` (the payload already carries `signatures`), and `test`
(sandbox only, a throwaway key; ETA will reject its signature, which is the point: it exercises the round trip
offline). More kinds can be registered through `einvoice_eta.signing.signer_factories`.

Per document, `country_fields["eta"]` may carry: `document_type`, `receiver`, `references` (UUIDs of the original
invoices for a credit or debit note), `exchange_rate` (for a non-EGP invoice), `lines` (per line overrides of
`itemType`, `itemCode`, `unitType`, `internalCode`, `taxableItems`, `itemsDiscount`, `valueDifference`, `discount`),
`default_taxes` (taxable items added to every line, for example `{"taxType": "T4", "subType": "W001", "rate": 1}`),
`extra_discount_amount`, and `date_time_issued`.

## Validation rules

Registered in the `einvoice_clearance` rule set, so the existing gate (`hard_blockers` before submit) runs them.
Each applies only to documents whose format is `eta_json_1_0`; elsewhere it passes.

| Rule id | Severity | Checks |
|---|---|---|
| `einvoice_clearance.eta_document_readable` | ERROR | Payload parses as one JSON object |
| `einvoice_clearance.eta_parties` | ERROR | Issuer type B, id equals the profile RIN, RIN valid per the shared check, branchID present, country EG; receiver type B/P/F; B receiver id (valid RIN) and name; F receiver country not EG; receiver differs from issuer |
| `einvoice_clearance.eta_header` | ERROR | documentType known, version 1.0, dateTimeIssued UTC and not in the future, activity code in ETA's table, internalID present, at least one line, references for credit and debit notes |
| `einvoice_clearance.eta_lines` | ERROR | itemType GS1/EGS, itemCode present, unitType in ETA's table, quantity > 0, non-EGP lines carry amountSold and exchange rate, discount rate 0-100, each taxType once per line, subtype belongs to its type, T3/T6 rate 0, rate 0-999 |
| `einvoice_clearance.eta_totals` | ERROR | Line equations (sales total, discount, net, T5-T20, T2, T1, T4, line total) and document totals (sales, discount, net, items discount, tax totals, total amount) |
| `einvoice_clearance.eta_advisory` | WARNING | P receiver without id at or above the threshold of the issue date, EGS code without the `EG-` prefix, RIN format not checked, text values with `"` or `\`, document totals over 5 decimals |

`einvoice_clearance.eta_profile` (ERROR, intent submit or cancel) checks the profile settings the adapter needs:
environment matching the sandbox flag, both base URLs, both credential variable names, and a signer.

## Test plan

Tests first, in `backend/tests/unit/test_einvoice_eta_*.py`, with the SDK's own files as fixtures
(`backend/tests/fixtures/eta/`, copied from https://sdk.invoicing.eta.gov.eg/files/):

1. Serialization: `one-doc.json` serializes byte for byte to `one-doc-serialized.json.txt`. Distinguishing cases:
   `947.00` must stay `947.00` (a float round trip prints `947.0`), arrays repeat the array name before every
   element, nested objects are not prefixed twice.
2. Hash: SHA-256 of that serialization equals the `messageDigest` inside the CAdES-BES of the signed sample
   `one-doc-I.json` (`D43FAE25...`). This proves the hash ETA signs is the hash of our serialization.
3. Signature structure: given the certificate, signing time and RSA value taken out of the signed sample, the CMS
   builder reproduces the sample's signature bytes exactly, and the sample's RSA value verifies against the DER
   of our signed attributes with the certificate's public key. A test signer's output verifies the same way.
4. Calculation: every line and document equation holds on `one-doc.json`, which carries all twenty tax types on
   each line. One unit in the last decimal place passes (D9) and two units are found with the line's path; VAT
   computed on the net alone is found; a document total that ignores the extra discount is found. A hand-worked
   line with a discount, T1, T2, T4 and T5 pins the order of the equations.
5. Builder: a finance invoice with two lines at 14% produces a `documentType` `i`, version `1.0`, T1/V009 lines
   whose totals pass the checker; a credit note carries references; a USD invoice carries `amountSold` and the
   exchange rate and converts to EGP.
6. Rules: each rule passes on a document the builder produced, fires on the defect it names with the JSON path,
   passes on a non-ETA document, and does not judge the document on a cancel. The ERROR rules join the hard gate
   that runs before an adapter is called. The SDK's own sample is version 0.9 with `GPC` item codes; the checks
   say exactly that about it and find no arithmetic fault.
7. Client: with an `httpx.MockTransport`, login sends Basic auth and `grant_type=client_credentials`, the token is
   cached until expiry, `onbehalfof` is sent when configured, a 401 triggers one fresh login, submit maps 202
   accepted and rejected documents, 422 `DuplicateSubmission` raises with `Retry-After`, cancel sends the
   `{"status": "cancelled", "reason"}` body.
8. Adapter: submit returns pending with the ETA UUID; poll maps `valid` to accepted and `invalid` to rejected with
   the failing validation step messages; cancel refuses locally when the workflow window has passed; a test signer
   is refused on a live profile; a missing base URL is refused before any request.
9. Service (PostgreSQL lane, `test_einvoice_clearance_module.py`): a pending outcome leaves the document
   `submitted` with the identifier stored; `refresh` moves it to `cleared`, or to `rejected` on an invalid
   verdict; an adapter without `poll` refuses `refresh` with a message naming the manual resolve.

## What remains for a live pilot (partner)

1. Taxpayer onboarding on the ETA portal: register the ERP system and obtain the client id and secret for
   pre-production, then separately for production (they differ).
2. Check the identity and API hosts in the ETA onboarding pack against the defaults from the SDK FAQ.
3. Obtain an eSeal certificate from an ITIDA-licensed CA, install the token or HSM middleware on the signing
   machine, and either install `python-pkcs11` on the server that holds the token or run a signing service that
   implements the `external_http` contract.
4. Register EGS item codes (or map GS1 codes) for the company's services and set the default item code; confirm
   the platform unit to ETA unit map and the VAT category to subtype map with the company's tax advisor.
5. Send a pre-production invoice, credit note and cancellation; read the cancellation workflow parameters that
   Get Document Type returns and record them in the regime notes.
6. Decide polling against callbacks. Polling is implemented; ETA recommends callbacks, which need a public
   endpoint on the ERP side.
