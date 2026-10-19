# France, core stream: payment law, works contracts, estimating, calendar, labour

Status: built on `wip/fr-core-20261019` from `integration/18.7.0-20261017`. The e-invoicing reform, the
SIREN/SIRET validators and the new invoice mentions belong to the `fr-einv` stream and are not touched here.

Every French number below ships as data with its source and the date it took effect. Facts the research
marked UNCONFIRMED are either left out with the reason written here, or shipped as editable rows flagged
`needs_expert_review`, which a screen can show and no rule can enforce.

## 1. Late payment (payment_clock)

### What was wrong

France had no row in `PAYMENT_REGIMES`, so a French clock could only be opened on `eu_late_payment`,
which states the Directive's ECB + 8 points. That is right for public buyers by coincidence and wrong for
every private B2B invoice, where the French default is ECB + 10 points (C. com. L441-10 II).

### Rows added

| code | buyer | final date | interest | source |
|---|---|---|---|---|
| `fr_com_l441_10` | business to business | 30 days after receipt or performance (default when the contract is silent) | ECB + 10, rate of 1 Jan for H1 and 1 Jul for H2 | C. com. L441-10 I and II, D441-5 |
| `fr_ccp_r2192_10` | State, local authorities, most public bodies | 30 days | ECB + 8, fixed at the half-year interest starts | CCP R2192-10, R2192-31 |
| `fr_ccp_r2192_11_health` | public health establishments | 50 days | as above | CCP R2192-11 |
| `fr_ccp_r2192_11_undertaking` | public undertakings | 60 days | as above | CCP R2192-11 |

Four rows rather than one with a footnote: a regime in this table is one clock, and a footnote is not
something a calculation can read (the same reasoning that made VOB/B two rows).

### Decision: one late payment engine

There is exactly one engine for dated statutory interest, term caps and recovery compensation:
`app/core/late_payment.py` over `app/core/country_data/late_payment.json` (pl-core, Poland first). The
`payment_clock` module keeps only the notice regimes (which day is the final date), so the four French
rows above stay here and nothing else. An earlier draft of this stream added a second engine
(`payment_clock/reference_rates.py`, with a rate-fixing model and an agreed-term-cap rule); it was removed
and the French interest row is data in `late_payment.json`. The public regime's single rate for the
whole delay (R2192-31) and the agreed-rate floor are described in `docs/design/france/late_payment.md`.

## 2. and 3. Works contracts, warranties and VAT

Moved to `docs/design/france/contracts.md` (branch `wip/fr-contracts-20261019`).

## 4. Estimating

Three FR markup sets disagreed: `boq/markup_templates.py` (FC 10, FG 15, B&A 8, on direct cost), the
methodology literal (12 / 7, overwritten at import by the table already) and the Lyon demo (9 / 12 / 5 /
contingency 6). None is a legal figure. Decision: `markup_templates.py` stays the one source, the
methodology literal is set to say the same thing, and the Lyon demo reads its lines from that table plus
the project-specific contingency, so a change of the national stack reaches the demo.

DPGF already exists as an exchange format. BPU (unit price schedule) and DQE (estimated quantities priced
by the BPU) are added as workbook rows of the exchange catalogue, read and written by the spreadsheet
importer and exporter in French headings.

## 5. Calendar and labour

- `app/core/calendar.py` gets `_holidays_fr` (C. trav. L3133-1, 11 days computed for any year) and the
  Monday to Friday week. Subdivisions FR-57, FR-67, FR-68 (and FR-6AE, the Alsace European collectivity)
  add Good Friday and 26 December (C. trav. L3134-13). The 2026 seed stays and must agree with the engine.
- Labour facts: `docs/design/france/labour.md` (branch `wip/fr-labour-20261019`).

## Test plan (distinguishing cases)

- Four French notice regimes exist with their own periods and margins; the private default is two points
  above the Directive row.
- Calendar: 2027 France includes 2027-03-29 and 2027-05-06 and not 2027-03-26; FR-57 2027 includes
  2027-03-26 and 2027-12-26; FR (national) 2027 does not include 2027-12-26.
