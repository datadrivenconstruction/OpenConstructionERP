# Procurement profiles, schema v2

One JSON file per jurisdiction (`EU`, an ISO 3166-1 country such as `DE`, or an
ISO 3166-2 subdivision such as `DE-BY`). The model lives in `../profile.py`.

## Header

`jurisdiction`, `parent` (the level it overrides: `DE` names `EU`, `DE-BY` names
`DE`), `legacy_codes` (v1 catalogue codes it answers for, e.g. `de_national`),
`authority_types`, `private_authority_type`.

## Sections

| Section | Content |
| --- | --- |
| `thresholds[]` | contract type, authority type, effect, net/gross basis, lot aggregation, amount |
| `procedures[]` | minimum deadlines per variant, minimum invitations, justification required |
| `publication[]` | channel, format and version, when mandatory (`always`, `above_threshold`, ...) |
| `requirements[]` | neutral requirement code and stage (`submission` ... `execution`) |
| `award` | criteria, weights published, abnormally low rule |
| `notification` | standstill days per channel |
| `signature` | `eidas` or `local`, bid level `text_form`, `advanced` or `qualified` |
| `locale` | languages, currency, VAT basis |

Every legal value is wrapped:
`{value, unit, source_url, source_ref, retrieved_at, confidence, review_status,
confirmed_by, confirmed_at, effective_from, effective_to}`.

## Rules (CI gate: `tests/unit/test_procurement_profile_v2.py`)

- Every value needs `source_url` and `effective_from`. Never invent a value; leave it out.
- Jurisdiction and parent codes must be known; the parent chain must not cycle.
- Time slices of one path must not overlap. A child file holds only its overrides.
- Shipped values stay `review_status: unconfirmed`.

## Resolution and the gate

The chain is merged root first (EU, country, subdivision); the most specific
level wins per path. On a given day the slice in force is taken; if only an
expired one exists it is used and marked `stale`. A value is `confirmed` only
when this instance confirmed that exact value (path and hash) in
`oe_procurement_concept_profile_confirmation`. Unconfirmed and stale values
produce warnings with their source and never block. The rule snapshot records
the status of each value the procedure test read.

## v1 catalogues

`migrate_v1()` derives these files from `../catalogues/*.json`. Values without a
source or a start date are reported as gaps, not carried over.

## DE

Jeder Rechtswert braucht Quelle (`source_url`) und Gültigkeitsbeginn
(`effective_from`). Ausgelieferte Werte sind unbestätigt und warnen nur; jede
Instanz bestätigt sie selbst nach Prüfung an der Quelle.

## RU

Каждое правовое значение требует источника (`source_url`) и даты вступления в
силу (`effective_from`). Поставляемые значения не подтверждены и только
предупреждают; каждая инсталляция подтверждает их сама после проверки по источнику.
