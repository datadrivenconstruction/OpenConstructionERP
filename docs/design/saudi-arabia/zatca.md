# Saudi Arabia: ZATCA FATOORA phase 2 (stream `zatca`)

Status: implemented on `wip/sa-zatca-20261019`. The document, hash, stamp and QR were checked offline against
the official ZATCA SDK; the onboarding client, adapter and rules are tested against a fake gateway. Not yet run
against the FATOORA developer portal or simulation, which needs a taxpayer OTP (see "What remains for a live
pilot").

Sibling streams: `sa-core` owns Saudi tax rates, contracts, labour and the Saudi partner pack files;
`eg-eta` owns the country-neutral `einvoice_clearance` extension this stream builds on (cherry-picked as one
commit, never forked). The shared clearance changes are, in order: the pending outcome and polling (eg-eta),
the regime `extra` serialisation (fr-einv), and a per-outcome `act` (this stream, one small commit of its own).

## Scope

ZATCA e-invoicing phase 2 ("integration") for a Saudi VAT taxpayer that issues construction invoices. Legal
basis: the E-invoicing Regulation (ZATCA Board, 2020-12-04) and the "Controls, Requirements, Technical
Specifications and Procedural Rules". Phase 2 is a split model. Standard tax invoices (B2B and B2G, KSA-2
`01xxxxx`) are cleared by ZATCA before they reach the buyer. Simplified tax invoices (B2C, KSA-2 `02xxxxx`) are
stamped by the seller and reported within 24 hours.

In scope:

1. The SA row of the clearance regime registry gains its second act (reporting) and the dated integration
   waves 1 to 25, each with its source.
2. A plugin package `backend/app/modules/einvoice_zatca/` that produces the UBL 2.1 KSA profile document from a
   finance invoice. It covers type codes 388, 381, 383 and 386, the KSA-2 subtype flags, the ICV counter and
   the PIH hash chain per EGS unit, the XAdES B-B enveloped signature (ECDSA secp256k1 with SHA-256) behind a
   pluggable signer, and the QR TLV with tags 1 to 9.
3. EGS unit onboarding as a documented state machine: key pair and CSR, then compliance CSID (OTP), then
   compliance checks per document type, then production CSID, then renewal.
4. A FATOORA REST client (compliance CSID, compliance invoices, production CSID and renewal, clearance, reporting)
   behind the clearance adapter interface and an injectable `httpx` transport. No test reaches ZATCA.
5. Pre-submit validation as rules in the `einvoice_clearance` rule set (so they gate submission): the BR-KSA
   rules the document can be checked against offline, signature and hash integrity, and the construction VAT
   rules of the 2026 contracting guideline.
6. Saudi party identifiers in `app/core/party_identifiers/sa.py`: VAT registration number and Commercial
   Registration number.
7. The dangling `sa_vat_15` tax template name gets a defined meaning (D11).

Out of scope here: the PDF/A-3 visual invoice, the inbound side (receiving invoices other taxpayers clear to us),
a frontend screen for EGS onboarding (the API is complete; the clearance screens already list documents and
their status), and the e-invoicing penalty schedule (no official text read, see UNCONFIRMED).

## Sources

All read 2026-10-19 unless stated.

| Ref | Document | URL |
|---|---|---|
| P1 | ZATCA Electronic Invoice XML Implementation Standard v1.2 (2023-05-19) | https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf |
| P2 | ZATCA Electronic Invoice Security Features Implementation Standards v1.2 (2023-05-19) | https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards_vF.pdf |
| P3 | Fatoora Detailed Guidelines for E-Invoicing v2 (May 2023) | https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-Invoicing_Detailed__Guideline.pdf |
| P4 | VAT Guideline for the Contracting Sector, second issue (May 2026) | https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/Guideline-For-the-Contracting-Sector-under-VAT-Provision.pdf |
| P8 | E-invoicing Regulation (2020-12-04) | https://zatca.gov.sa/en/E-Invoicing/Introduction/LawsAndRegulations/Documents/E-invoicing-Regulations.pdf |
| SDK | ZATCA E-Invoicing SDK 238-R3.3.8 (November 2024), linked from the developer portal configuration `REACT_APP_DOWNLOAD_SDK_LINK` at https://sandbox.zatca.gov.sa/env-config.js. Archive sha256 `5d9a57df5bbbc0a5aff41b81201ff94dc4189158bd0d82301ebff9a027b0d80f`. LGPL-3.0. | https://sadzit.sharepoint.com/:u:/g/EV2GE3hw-x1KqGdTwqNS7OUBBYEwN9r_OSAx9vErGQ7r5Q |
| API | FATOORA developer portal configuration (base paths of the sandbox, simulation and production gateways) | https://sandbox.zatca.gov.sa/env-config.js |
| EY | Saudi Arabia announces 25th wave (2026) | https://taxnews.ey.com/news/2026-1705-saudi-arabia-announces-25th-wave-of-phase-2-e-invoicing-integration |
| KPMG | E-invoicing mandatory above SAR 187,500 (2026-07) | https://kpmg.com/us/en/taxnewsflash/news/2026/07/saudi-arabia-e-invoicing-mandatory-for-taxpayers-with-revenue-above-sar-187500.html |

The SDK is the authority for the exact bytes. Where its samples and the standard's prose disagree, the
package follows the samples, because the SDK is what ZATCA's own validator runs. Each such case is listed
under D5.

## Architecture decisions

**D1. A plugin package, not code in `einvoice_clearance`.** `einvoice_zatca` depends on
`oe_einvoice_clearance` and, on startup, registers into its registries: the adapter registry
(`zatca_fatoora`), the payload builder registry (format `zatca_phase2`) and the clearance rule set. It also
mounts its own router for EGS units and onboarding. Removing the folder removes ZATCA without touching the
clearance module. The clearance extension (pending outcomes, polling, payload builders, gate rules) is
eg-eta's commit `71fcb5308`, cherry-picked unchanged.

**D2. No new dependency.** Signing uses `cryptography`, which is already in the lockfile through
`python-jose[cryptography]` and supports secp256k1. HTTP goes through `httpx`, already a core dependency.
Canonicalization is the one piece the standard library cannot do: `xml.etree.ElementTree.canonicalize`
implements C14N 2.0, which moves namespace declarations to first use and so changes the hash. `lxml` is a
test-only dependency here. `c14n.py` carries the part of C14N 1.1 an invoice needs (about 300 lines, expat
based, refuses DTDs). It reproduces the DigestValue of every official SDK sample byte for byte, and that is
pinned in the tests.

**D3. Sign at build time; the stored payload is the final signed XML.** The clearance service hashes and
stores the payload when the document is created and sends exactly those bytes later. So the builder
allocates the ICV and PIH, signs and writes the QR in one step, and the document row holds what ZATCA will
receive. The invoice hash excludes the signature, the QR and the extensions, so stamping cannot move the
chain.

**D4. Both standard and simplified invoices are signed.** For a simplified invoice the seller's stamp is
legally required (BR-KSA-60). For a standard invoice ZATCA stamps it at clearance and generates the QR
(P3 FAQ: "the QR Code string will be generated by ZATCA at the time of Clearance"). The package still signs
standard invoices, because the compliance-check step validates the stamp of every sample, and ZATCA replaces
it on clearance. The cleared XML that ZATCA returns, with ZATCA's stamp and QR, is stored with the
submission's response (`raw_response.cleared_invoice`) and is the document to give the buyer.

**D5. Hashing and signature follow the SDK, verified against its validator.**

- The invoice hash is SHA-256 of C14N 1.1 of the document without `ext:UBLExtensions`, `cac:Signature` and
  the `AdditionalDocumentReference` whose ID is `QR`. It is base64 of the raw digest (BR-KSA-26 and P2).
- The signature value is ECDSA with SHA-256 over the 32 raw bytes of that hash, not over `ds:SignedInfo` as
  in plain XMLDSig. The SDK verifies it that way.
- The CertDigest and the SignedProperties digest are base64 of the hex text of a SHA-256, not of the raw
  digest. The SignedProperties digest is taken over the element as it appears in the document, with its two
  namespace declarations written in. The SDK recomputes both from the document.
- In the QR, tags 6 and 7 carry the base64 text of the hash and the signature (44 and about 96 bytes). P2
  says "32 bytes" for tag 6. Every official sample and the SDK's own QR check use the text, so the package
  does too. This is recorded as a discrepancy, not resolved by guessing.
- The first PIH of every EGS unit is base64 of the hex SHA-256 of `0` (BR-KSA-26; the SDK's `pih.txt`).

**D6. EGS units and the chain live in two tables of their own.** The ICV must never reset or repeat on a unit,
and the PIH must be the hash of the unit's previous invoice (P3 §6.5 lists a counter reset and a second chain
per unit as prohibited functions). The registration's `settings` JSON cannot hold that: replacing a
registration overwrites it whole. So `oe_einvoice_zatca_egs_unit` holds one unit (onboarding state,
certificates, encrypted secrets, chain head) and `oe_einvoice_zatca_chain_entry` holds one row per generated
document, unique on (unit, ICV). The builder takes the unit row `FOR UPDATE` (PostgreSQL) before it reads the
head, so two concurrent builds cannot share a counter. The unique constraint is the backstop. A rejected or
abandoned document keeps its place in the chain: the chain is over generated documents (P3 §6.5), and the next
document points at it. The migration is `v197_sa_zatca_egs_units` with down revision `v94_payment_release`
(the integration lead chains it). The hash columns are 128 characters wide: the first PIH is 88 characters. A
document UUID is unique across all units, because the adapter finds the unit that built a document through it.

**D7. Credentials are stored encrypted, never returned, never in a validation context.** The production CSID
token and secret come from the FATOORA API at onboarding, so they cannot be environment variables the operator
sets beforehand. They are stored with `app.core.crypto.encrypt_secret` (Fernet). The private key for the
`stored_key` signer is generated on the server, encrypted the same way, and has no export endpoint (P3 §6.5
prohibits exporting stamping keys). The adapter reads the decrypted credentials through an injectable loader.
It never writes the database, which keeps the adapter contract of `einvoice_clearance` intact.

**D8. The signer is pluggable.** `Signer` signs a 32-byte hash and exposes its certificate. Kinds: `test` (a
throwaway secp256k1 key and a self-signed certificate made in process, refused on a live registration),
`stored_key` (the encrypted key from D7) and `external_http` (posts the hash to a signing service the
deployment runs, for an HSM). A PKCS#11 signer is not shipped. The `external_http` hook covers an HSM without
a native dependency.

**D9. Clearance or reporting is decided per document by KSA-2.** The SA row keeps `clearance` as its deciding
act and adds `reporting` in `additional_regimes`. The adapter reads the subtype from the payload and calls
`/invoices/clearance/single` for `01xxxxx` and `/invoices/reporting/single` for `02xxxxx`. The adapter names the
act in the new optional `SubmissionOutcome.act` (default `None`, which keeps every other adapter as it was), and
the clearance service records `cleared` or `reported` from it. It honours the act only if the country's regime
declares it, so no adapter can turn a delivery receipt into a tax clearance by naming it. The adapter finds the
unit, and with it the CSID, through the document's UUID in the chain, so a document is only ever sent with the
credentials of the unit that stamped it. A cleared standard invoice keeps ZATCA's stamped XML in the event's
`raw_response.cleared_invoice`.

**D10. Construction VAT rules are data plus validators, read from P4.**

| Rule | P4 | Effect here |
|---|---|---|
| VAT is due on the full invoiced amount, retention included; the retention release needs no invoice and no VAT | §5.2, Example 4 | The builder bills the gross (finance `amount_total` is gross, `retention_amount` is held separately) and never subtracts retention. A document marked `retention_release` is refused with the guideline reference. |
| A down payment is taxed on receipt with a tax invoice | §5.3, Example 5 | Advances are type 386. A later invoice that deducts them carries the prepayment lines (KSA-26, 28 to 34) and `PrepaidAmount`. |
| Liquidated damages reduce the consideration: credit note with VAT | §5.4, Example 6 | `liquidated_damages` must be a 381 with a billing reference and VAT at the standard rate. Actual damages or court compensation are not adjustments, so a credit note for them is refused. |
| Government contracts: tax point is the earlier of the payment order date and receipt, main contractor only, claims from 2021-11-01 | §4.2 (VAT IR Art 20 amended; ZATCA Board 06-02-21) | Data row with a validator: a document marked as a government claim must state the payment order date or the receipt date. The validator says which one sets the tax point. A subcontractor flag switches the rule off. |
| A security deposit held in a separate account is out of scope | §5.3 | Data row only (no invoice is built for a deposit). |

Negative lines and negative totals are refused on every type. BR-KSA-F-04 requires positive amounts, and a
reduction is a 381.

**D11. `sa_vat_15` is defined, not invented.** The Saudi pack names `sa_vat_15` as its default tax template,
and no template of that name exists anywhere. Every pack's `default_tax_template` is in fact a name with no
resolver: the partner pack applier records it "for reference". The package defines the name in data as the
`SA`/`VAT` row of the dated tax seed (15% from 2020-07-01, 5% from 2018-01-01 to 2020-06-30, the second row
added by `sa-core`). The builder takes the standard rate for an invoice from that dated table, not from a
constant. A test checks that the pack's declared template resolves to a seeded row. The pack files are
`sa-core`'s and are not edited here. A resolver for all packs is a platform decision for the founder.

**D12. Integration waves are dated data on the SA row.** Each wave is one `CommencementPhase` with obligation
`issue`, the threshold in SAR, the reference years and, as `effective_date`, the end of its integration window
(the date by which the taxpayer must be integrated). Wave 25 (revenue above SAR 187,500 in any of 2022 to
2025, deadline 2027-02-01) is `enacted`; waves 1 to 24 are `in_force`. Phase 1 (generation, 2021-12-04) is
its own row. The historical table is as reproduced by EY (medium confidence), and each of those rows says so
in its notes.

## Data model

`oe_einvoice_zatca_egs_unit`

| Column | Meaning |
|---|---|
| profile_id | FK to the clearance registration (cascade) |
| unit_key | the EGS identifier, unique per registration; also the CSR common name |
| csr_fields | JSON: the CSR subject and extension fields (serial number `1-<solution>|2-<model>|3-<serial>`, organisation unit and name, VAT number, `invoice_type` as four digits TSCZ where `1100` is standard and simplified, location, industry) |
| state | onboarding state (below) |
| environment | the Fatoora environment (`developer_portal`, `simulation`, `production`) |
| signer_kind | `test`, `stored_key`, `external_http` |
| signer_config | non-secret signer settings (the URL of an external signer) |
| private_key_encrypted | Fernet token of the PEM key, `stored_key` only |
| csr_pem | the CSR sent with the OTP |
| compliance_token, compliance_secret_encrypted, compliance_request_id | the compliance CSID (the token is the certificate and is not secret) |
| production_token, production_secret_encrypted, production_request_id | the production CSID |
| certificate_not_after | expiry of the active certificate |
| compliance_results | JSON: document kind to ZATCA's verdict on the last compliance check |
| last_icv, last_hash | the chain head |
| last_error | the last refusal ZATCA gave this unit |

`oe_einvoice_zatca_chain_entry`: unit_id, icv, invoice_hash, previous_hash, invoice_uuid, invoice_number,
type_code, subtype, issued_at, invoice_id. Unique (unit_id, icv) and unique invoice_uuid.

### Onboarding state machine

```
new --csr--> csr_ready --otp: compliance CSID--> compliance_issued
compliance_issued --compliance check per required kind--> compliance_passed
compliance_passed --production CSID--> active
active --renew (new OTP + CSR)--> active          (PATCH production/csids)
any --revoke--> revoked                            (terminal; a new unit is onboarded)
```

The required kinds follow `invoice_types`: for each of standard and simplified the unit is configured for, one
388, one 381 and one 383 must pass (the SDK's compliance set). A unit signs documents for a sandbox
registration from `compliance_issued` on, and for a live registration only when `active`.

## Validation rules (all in `einvoice_clearance` rule set, ERROR unless stated)

- `zatca_document_readable`: the payload is one UBL Invoice in the namespaces the KSA profile uses.
- `zatca_header`: ProfileID `reporting:1.0`, UUID, IssueDate `YYYY-MM-DD` not in the future, IssueTime, type
  code in 388/381/383/386, KSA-2 seven flags with BR-KSA-31 limits, SAR tax currency, ICV digits, PIH base64
  SHA-256, BT-25 and KSA-10 on 381/383.
- `zatca_parties`: seller VAT (15 digits, 3...3), seller ID scheme, seller address with a four-digit building
  number and five-digit postal code; buyer address and identifier for a standard invoice with an SA buyer; no
  buyer VAT on an export.
- `zatca_lines_totals`: VAT categories and VATEX codes, line and document equations (KSA-11, KSA-12, BT-106 to
  BT-115) at two decimals, half-up, two TaxTotals with the SAR one, positive amounts.
- `zatca_stamp`: the recomputed hash equals the signed DigestValue, the SignedProperties and certificate
  digests match, the signature verifies against the embedded certificate, and the QR decodes to the document's
  own values. Required on simplified documents, checked on standard ones when present.
- `zatca_construction_vat`: the D10 rules on the document's ZATCA fields.
- `zatca_advisory` (WARNING): what ZATCA's validator reports as warnings, including a government claim with no
  payment order date.
- `zatca_reporting_deadline` (WARNING): a simplified document submitted more than 24 hours after its issue time.
- `zatca_profile`: the registration's tax registration id is a Saudi VAT number.

Rules are pure, as the rule set requires, so whether the registration has an EGS unit able to stamp is not a rule.
The builder refuses to build without one (a live registration needs an `active` unit whose certificate has not
expired), and the adapter refuses to send a document whose unit has no usable CSID.

The onboarding API is `/api/v1/einvoice-zatca/` (`meta`, `units/`, and per unit `csr`, `compliance-csid`,
`compliance-checks`, `production-csid`, `renew`, `revoke`). Permissions: `read`, `manage` (editor), `onboard`
(manager, because it spends the taxpayer's one-time password and changes a certificate).

## Test plan (distinguishing cases)

Golden values come from the SDK 238 run locally on our output (Java 11, `fatoora -validate`). Each value is
pinned in the test, so CI needs no Java.

1. C14N: the hash of every signed official sample (Standard and Simplified Invoice, Credit, Debit) equals its
   embedded DigestValue. Distinguishing: the stdlib C14N 2.0 gives a different hash on the same input, and the
   test asserts that too, so a "simplification" back to the stdlib fails.
2. Signature: the official samples' SignatureValue verifies over the raw hash bytes with the sample
   certificate, and does not verify over SignedInfo. Our signer's output verifies the same way.
3. SignedProperties and CertDigest: recomputed from the sample documents equal to the embedded values; a
   changed SigningTime changes the digest.
4. QR: decoding the samples' QR gives tags 1 to 8 (standard) and 1 to 9 (simplified) with the values the
   document carries; our encoder round-trips them; over 700 characters is refused.
5. Builder: a construction interim invoice with retention builds a 388 whose taxable amount is the gross
   (retention not subtracted). Its XML validates against the UBL 2.1 XSD (lxml, test-only) and its hash,
   digests and QR pass the `zatca_stamp` rule. Distinguishing: the same invoice with retention subtracted is
   the wrong VAT, and the test pins the VAT figure of P4 Example 4 (5,000,000 gives 750,000).
6. Chain: three documents on one unit get ICV 1, 2, 3; the first PIH is the seed, and each next PIH is the
   previous hash. A second unit starts its own chain at the seed. A duplicate (unit, ICV) insert is refused by
   the database.
7. Types: 381 without a billing reference is refused; 386 advance and a later 388 with the prepayment lines
   give `PrepaidAmount` = KSA-31 + KSA-32; LDs as a 381 at 15% (P4 Example 6: 440,000 + 66,000 = 506,000).
   Retention release and actual damages are refused with the guideline paragraph.
8. Rules: each BR-KSA rule the validator carries has one failing and one passing document.
9. Adapter: with an `httpx.MockTransport`, a standard document goes to `/invoices/clearance/single` with
   `Clearance-Status: 1` and a simplified one to `/invoices/reporting/single`. 200 and 202 (warnings) are
   accepted; 400 maps to a rejection with ZATCA's codes; 401 and 5xx raise (transport). The cleared XML is kept.
10. Onboarding: the state machine refuses every transition the diagram does not draw; a CSR made by the package
    carries the ZATCA template extension and the subject fields; compliance CSID, compliance checks and
    production CSID run against the mock transport.
11. Party identifiers: VAT `300000000000003` valid, `310000000000003` valid, 14 digits invalid, a VAT that does
    not start or end with 3 invalid; CR 10 digits valid, 9 invalid.
12. Regime data: 25 waves plus phase 1, all sourced; wave 25 is 2027-02-01 with SAR 187,500 and reference years
    2022 to 2025; the SA row is hybrid with reporting.

## UNCONFIRMED (shipped as editable data flagged `needs_expert_review`, never as hard rules)

- Wave 25 as the last wave (EY: "monitor future announcements").
- The historical wave table 1 to 24 as reproduced by EY; wave 22 dates in particular.
- OTP lifetime (about 1 hour) and compliance CSID validity (about 24 hours): not stored as numbers; the API's
  own answer decides.
- The production gateway paths: taken from ZATCA's own portal configuration, but not yet exercised.
- The QR tag 6 and 7 encoding (D5): the samples and the standard disagree.
- The e-invoicing penalty schedule: no official text read; not shipped.

## What remains for a live pilot

An OTP from the taxpayer's FATOORA portal; one onboarding run against the developer portal, then the
simulation environment; a decision on where the stamping key lives in production (`stored_key` on the server
or an HSM behind `external_http`); and an expert reading of the construction rules against the taxpayer's
actual contracts (government claims especially).
