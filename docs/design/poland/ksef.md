# Poland: KSeF 2.0 e-invoicing with FA(3)

Status: built on branch `wip/pl-ksef-20261019`. Facts read 2026-10-19.

## Why

Poland clears every B2B invoice through KSeF (Krajowy System e-Faktur). The platform had a
regime row for Poland that named the retired FA(2) schema, carried no phase dates and could not
produce a document, so a Polish contractor could not issue a single compliant invoice from the
platform. Since 2026-02-01 the only accepted structure is FA(3), and from 2027-01-01 the
penalties start and the KSeF number becomes mandatory in the payment title.

## Scope

1. Correct the regime row: FA(3), its namespace, the phase dates by taxpayer size, the token
   authentication end, the penalty start, with sources. FA(2) stays as a historical row with an
   end date.
2. FA(3) XML generator from the finance invoice, validated against the official XSD in the tests.
   Covers the basic invoice (VAT), the corrective invoice (KOR), the advance invoice (ZAL), the
   settlement invoice after advances (ROZ), the split payment annotation P_18A and the Annex 15
   line marker, reverse charge, cash accounting, contract references (construction contracts).
3. Offline modes (offline24, offline for unavailability, failure, total failure) as data, with the
   upload deadline computed per mode; the two QR codes (KOD I with the KSeF number or "OFFLINE",
   KOD II "CERTYFIKAT" signed with the offline certificate).
4. KSeF number stored against the invoice and required in payment titles from 2027-01-01, as a
   date-effective validation rule (warning in 2026, error from 2027).
5. KSeF API 2.0 client (challenge, token authentication, online session, send, status, UPO) behind
   the clearance adapter boundary. Never called in tests.
6. JPK_V7(3) per-document marker (KSeF number or OFF / BFK / DI). There is no JPK export in the
   platform today; the marker is exposed as a function for the export that does not exist yet.
   Gap recorded below.

Out of scope: receiving invoices from KSeF (download, incremental fetch), batch sessions,
KSeF certificate enrolment, PEF (B2G via Peppol) and FA_RR, the JPK_V7 file itself.

## Architecture

A plugin package `backend/app/modules/einvoice_ksef/`, the same shape as Egypt's `einvoice_eta`.
It adds no tables, no routes and no migration. On startup it registers into the
`einvoice_clearance` registries:

* an adapter under key `ksef_pl` (countries `PL`),
* a payload builder for document format `ksef_fa_3` (the finance invoice becomes FA(3) XML),
* validation rules into the `einvoice_clearance` rule set (run by the submit gate) and into the
  `finance` rule set (payment title).

The extension points it uses (`register_payload_builder`, `SubmissionOutcome.pending`,
`PollRequest` and the optional `poll`, the refresh endpoint, plugin rules in the hard gate) are
the ones the Egypt ETA stream adds to `einvoice_clearance`. They are shared, not forked: KSeF is
asynchronous in the same way as ETA (a send returns a reference, the KSeF number and the UPO come
from a later status read), so one interface serves both.

| File | Role |
|---|---|
| `facts.py` | Dated, sourced facts as data rows: schema identities, phases, deadlines, environments, offline modes, JPK markers |
| `ksef_number.py` | KSeF number format and CRC-8 check |
| `fa3.py` | Neutral input dataclasses and the FA(3) XML writer; a reader for what the rules need |
| `split_payment.py` | Whether P_18A applies; the threshold and Annex 15 sections are read from the Polish VAT data (`app.core.vat_construction`) |
| `builder.py` | Finance invoice to FA(3) input; the registered payload builder |
| `offline.py` | Offline modes and upload deadlines |
| `qr.py` | KOD I and KOD II links, the link signer, QR rendering to SVG |
| `crypto.py` | AES-256-CBC for documents, RSA-OAEP SHA-256 for keys and tokens |
| `client.py` | The KSeF API 2.0 calls this platform needs |
| `adapter.py` | The clearance adapter: submit, poll, cancel (refused, KSeF has no cancellation) |
| `payments.py` | The KSeF number of an invoice and the payment title check |
| `jpk.py` | The JPK_V7(3) per-document marker |
| `validators.py` | The rules |

## Decisions

**Where the KSeF number lives.** For an invoice the platform issued, the number is the
`authority_identifier` of its cleared clearance document, which is linked by `invoice_id`. It is
not copied onto the finance invoice: a copy would be a second source of truth that can disagree
with the record the authority confirmed. For a received invoice there is no clearance document,
so the number is entered on the invoice as `metadata.ksef_number` through the existing invoice
API. The two populations are disjoint (outgoing and incoming), and one resolver
(`payments.ksef_number_for_invoice`) reads both.

**The pending handle.** While KSeF processes a document, the clearance document carries the
handle `ksef-ref:<session reference>/<invoice reference>` as its identifier, because the poll
needs both references. When the status read returns the KSeF number, the poll replaces the handle
with it. The prefix makes a handle impossible to mistake for a KSeF number, which has a different
shape and a checksum.

**P_18A is derived, not typed.** The builder sets P_18A = 1 when at least one line is flagged
Annex 15 (`P_12_Zal_15`) and the gross total in PLN exceeds 15,000. A line is flagged by data
(`country_fields.ksef.lines[i].annex_15`), never guessed: Annex 15 is a list of PKWiU codes and a
code prefix is not a reliable test. A line with a construction PKWiU (sections 41-43) that is not
flagged raises an advisory warning only. For a foreign-currency invoice the PLN equivalent needs
the exchange rate (`country_fields.ksef.exchange_rate`); without it the decision cannot be made
and the rule says so. The threshold (strictly above PLN 15,000) and the Annex 15 sections belong to
the Polish VAT data, `app.core.vat_construction`, and this module keeps no copy. If that data cannot
be read, P_18A is "not checked": the rules warn, and the builder uses the invoice's stored marker or
stops. It never falls back to a remembered number.

**Advance invoices.** ZAL carries the received payment in P_13_x / P_14_x / P_15 and the order or
contract it relates to in `Zamowienie` (value with VAT, and its lines). ROZ (the settlement invoice
after advances) lists the advance invoices in `FakturaZaliczkowa`, by KSeF number when they have
one and by their own number when issued outside KSeF. This is the common construction pattern: an
advance on a contract, then stage or final invoices that settle it.

**Corrections.** KOR carries `DaneFaKorygowanej` (date, number, and KSeF number of the corrected
invoice or the "issued outside KSeF" marker), the reason and the correction type (1, 2, 3). The
lines are the differences. KSeF has no cancellation; the regime row keeps
`cancellation_window_days=None` and the adapter refuses a cancel with the correction mechanism.

**Offline.** The mode is chosen on the document (`country_fields.ksef.offline_mode`). Upload
deadlines: offline24 and offline (unavailability) the next business day after issue or after the
end of the unavailability; failure (awaria) 7 business days after the end of the failure; total
failure no upload. Business days come from `app.core.calendar.add_working_days(..., "PL")`. The
platform's holiday table has no Polish holidays yet (that belongs to the calendar stream), so the
computed deadline can fall on a Polish holiday. That makes it earlier than the statutory one,
never later, which is the safe direction for a reminder.

**QR codes.** KOD I is `https://qr.ksef.mf.gov.pl/invoice/{seller NIP}/{P_1 as DD-MM-YYYY}/{SHA-256
of the XML file, Base64URL}` with the label set to the KSeF number, or "OFFLINE" before one exists.
KOD II is `https://qr.ksef.mf.gov.pl/certificate/{context type}/{context value}/{seller NIP}/{offline
certificate serial}/{invoice hash}/{signature}`; the signature is over the link without
`https://`, RSASSA-PSS (SHA-256, MGF1 SHA-256, salt 32) or ECDSA P-256 in IEEE P1363 form,
Base64URL. Label "CERTYFIKAT". The signing key never enters the platform: a `LinkSigner` protocol
is implemented by a software key for tests and by whatever holds the offline certificate in
production. QR images are rendered to SVG with reportlab's QR widget, which the platform already
ships, so no dependency is added.

**Authentication.** KSeF tokens work until 2026-12-31; from 2027-01-01 only certificates or
qualified signatures. The client implements token authentication (challenge, RSA-OAEP encrypted
`token|timestampMs`) and takes XAdES authentication through a pluggable signer that receives the
challenge document and returns the signed XML. Which one a registration uses is a profile
setting. A rule warns when a registration on token authentication approaches 2026-12-31 and
refuses it after.

**Validation at runtime and in tests.** The tests validate every generated document against the
official XSD with lxml (a test-only dependency, the same arrangement as the GAEB conformance
suite). At runtime the rules read the generated XML for the facts they need (namespace, form code,
P_1, P_18A, totals); full XSD validation at runtime would need lxml in production, which the core
does not carry, and KSeF validates against the schema itself and rejects with code 450.

**Facts as data.** Every date and number in `facts.py` carries its source URL, the date it was read
and a confidence. Items the research marked UNCONFIRMED do not become rules; they ship as data
flagged `needs_expert_review`.

## Data

`country_fields["ksef"]` on a clearance document (all optional except where a kind needs them):

| Key | Meaning |
|---|---|
| `kind` | `VAT` (default), `KOR`, `ZAL`, `ROZ`, `KOR_ZAL`, `KOR_ROZ` |
| `delivery_date` / `period_from`, `period_to` | P_6 or OkresFa |
| `place_of_issue` | P_1M |
| `cash_accounting`, `self_billing`, `reverse_charge` | P_16, P_17, P_18 |
| `exchange_rate` | PLN rate for a foreign-currency invoice (P_14_xW, split payment threshold) |
| `lines` | per-line overrides by position: `annex_15`, `pkwiu`, `gtu`, `vat_code` (`23`, `8`, `5`, `0 KR`, `zw`, `oo`, `np I`, ...) |
| `correction` | `reason`, `type` (1/2/3), `corrected`: list of `{number, date, ksef_number}` |
| `advance` | ZAL: `order_value_gross`, `order_lines`; ROZ: `advance_invoices`: list of `{number, ksef_number}` |
| `contracts` | list of `{number, date}`, written to WarunkiTransakcji/Umowy |
| `bank_account` | NrRB for Platnosc |
| `offline_mode` | `offline24`, `offline`, `awaria`, `awaria_calkowita` |
| `offline_event_end`, `offline_failure_end` | end of the announced unavailability or failure (ISO date); the deadline counts from it |
| `corrected_invoice_hash` | technical correction of a rejected offline invoice |

Profile settings `settings["ksef"]`: `environment` (`test`, `demo`, `prod`), `auth`
(`token` or `xades`), `context_type` (`Nip` default), `issuer` (`name`, `address_line1`,
`address_line2`, `country`), `offline_certificate_serial`, secret references (never the secrets).

## Sources (read 2026-10-19)

| Fact | Source | Confidence |
|---|---|---|
| FA(3) schema, namespace `http://crd.gov.pl/wzor/2025/06/25/13775/`, form code `FA (3)` / `1-0E` / variant 3 | https://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd ; MF repo `CIRFMF/ksef-docs` `faktury/schemy/FA/schemat_FA(3)_v1-0E.xsd` (byte-identical) | H |
| FA(3) mandatory from 2026-02-01, replaces FA(2) | https://ksef.podatki.gov.pl/informacje-ogolne-ksef-20/struktura-logiczna-fa-3/ | H |
| Phase 1: 2024 sales above PLN 200m issue from 2026-02-01; everyone receives from 2026-02-01 | EY tax alert; Sovos | H |
| Phase 2: everyone else issues from 2026-04-01 | same | H |
| Micro (monthly invoiced sales up to PLN 10,000) may issue outside KSeF until 2026-12-31 | Sovos; MDDP | M |
| Penalties from 2027-01-01 | Sejm interpellation z02943; akademialtca | M |
| Tokens valid until 2026-12-31, certificates only from 2027-01-01 | ksef.podatki.gov.pl integratorzy (new tokens); Comarch (end date) | M |
| KSeF number in payment titles from 2027-01-01 | getsix; ifirma | M |
| Offline modes and deadlines | MF `ksef-docs/tryby-offline.md` (10.07.2025) | H |
| QR KOD I / KOD II format, signature algorithms, labels | MF `ksef-docs/kody-qr.md` (21.08.2025) | H |
| KSeF number structure, CRC-8 poly 0x07 init 0x00 | MF `ksef-docs/faktury/numer-ksef.md` | H |
| API 2.0 base URLs `https://api[-test|-demo].ksef.mf.gov.pl/v2`, QR hosts | MF `ksef-docs/srodowiska.md`, `open-api.json`, `kody-qr.md` | H |
| Split payment: Annex 15 and gross above PLN 15,000; P_18A | VAT Act art. 108a ust. 1a, 106e ust. 1 pkt 18a; FA(3) XSD documentation of P_18A | H |
| JPK_V7(3): KSeF number per document, else OFF / BFK / DI; mandatory from February 2026 periods | Reg. MF of 12.12.2025 (Dz.U. 2025 poz. 1800) via jpk.info.pl and getsix; marker meanings via infor.pl, fakturowo.pl, Comarch help | M |
| JPK marker for an offline24 invoice without a KSeF number at filing time | sources disagree (OFF vs DI) | UNCONFIRMED, shipped as data `needs_expert_review` |

The XSDs in `backend/tests/fixtures/ksef/` are published by the Ministry of Finance under the
MIT licence (repository `CIRFMF/ksef-docs`, copyright 2025 Ministerstwo Finansow); the licence
text ships next to them.

## Test plan (distinguishing cases)

* Generator: a basic 23% invoice validates against the XSD; a mixed 23/8/zw invoice puts each base
  in its own P_13_x and the totals add up; KOR with a KSeF-issued original and one issued outside
  KSeF both validate and differ in exactly the NrKSeF / NrKSeFN choice; ZAL with an order block
  validates; ROZ lists advance invoices by KSeF number and by own number; a foreign-currency
  invoice writes P_14_xW in PLN.
* Split payment: Annex 15 line with gross 15,000.01 PLN gets P_18A = 1; the same at exactly 15,000
  gets 2; a gross above the threshold with no Annex 15 line gets 2; EUR invoice without a rate is
  undecidable and the rule says so; with a rate it decides on the PLN amount.
* Regime: PL row says `ksef_fa_3`, carries the three issue phases and the receive phase with
  sources; FA(2) is historical with an end date of 2026-01-31; the rule refuses an FA(2) payload
  dated on or after 2026-02-01 and accepts it before.
* KSeF number: the MF example `5265877635-20250826-0100001AF629-AF` passes; a changed checksum
  fails; the handle prefix is never accepted as a number.
* QR: KOD I for the MF example equals the MF example link; KOD II signed with a test RSA key
  verifies with RSASSA-PSS and with a test EC key in P1363 form; labels are the KSeF number,
  "OFFLINE" and "CERTYFIKAT".
* Offline deadlines: offline24 on a Wednesday is due Thursday; on a Friday it is due Monday;
  awaria ending on a Saturday gives 7 business days counted from it; total failure has no deadline.
* Payment title: a 2026 payment without the KSeF number is a warning, a 2027 payment is an error,
  a 2027 payment whose title carries the number passes, a payment of an invoice with no KSeF
  number at all (issued outside KSeF) is not flagged.
* Client and adapter: with `httpx.MockTransport`, the token flow encrypts `token|timestampMs`
  with the key published for `KsefTokenEncryption`; the send encrypts with AES-256-CBC and sends
  the hashes and sizes of both forms; status 100/150 is pending, 200 clears with the KSeF number
  and fetches the UPO, 4xx is a rejection with the KSeF code; a live profile is refused when the
  environment is not set. Nothing reaches the network.
* JPK marker: a cleared invoice gives its number; an offline invoice still without a number gives
  the configured marker; an invoice outside KSeF gives BFK; a non-invoice document gives DI.

## Gaps and questions for an expert

* JPK_V7(3) export does not exist in the platform. The marker function is ready for it.
* Offline24 invoices without a KSeF number at filing time: OFF or DI. Sources disagree.
* Polish public holidays are not in `core/calendar.py`; deadlines run on a Monday to Friday week.
* Receiving invoices from KSeF (purchase side) is not built; received KSeF numbers are entered.
* The micro exemption cap of PLN 450 per invoice reported by one source is not modelled.
* Finance publishes no event when a payment is recorded, so the payment title rule is not run
  automatically on save. `validators.evaluate_payment` runs it for one payment; wiring it into
  payment creation is a change to the finance module and is left for a reviewed follow-up.
* Many document rules read `country_fields.ksef`. Fields the operator never fills (an Annex 15
  flag, a PKWiU code) are not guessed, so the split payment rule only knows what it is told.
* NIP checksums come from the shared `app.core.party_identifiers` check (scheme `nip`). Where it is
  not installed, or its rule awaits expert review, `pl_ksef_nip_unchecked` warns and nothing blocks.
* The finance invoice may carry a split payment marker in `metadata["split_payment"]`, written by
  the Polish core pack. P_18A is still decided from the Annex 15 lines and the gross; the marker is a
  cross-check, and a disagreement stops the build rather than picking a side.
* The 2027 penalties are maximums (100% of VAT, 18.7% of gross where there is no VAT), stored on the
  regime row under `extra["penalties"]`. The legal basis (VAT Act art. 106ni) is read from a Sejm
  interpellation answer, not from the act itself.
