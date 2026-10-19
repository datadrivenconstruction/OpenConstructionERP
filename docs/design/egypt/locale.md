# Egypt stream: locale, digits, identifiers, right-to-left PDF

Status: implemented on `wip/eg-locale-20261019`. Owner: Egypt programme, locale stream.

## Why

An Egyptian implementation partner deploys the platform for Egyptian contractors. Four things
stood between an Egyptian estimator and a product that reads naturally to them:

1. The Arabic interface missed 180 keys and carried about 350 values copied from English.
2. Arabic always printed with Arabic-Indic digits (the `ar` language resolves to `ar-SA`), and
   nothing let a reader or a document choose Western digits, which Egyptian business documents
   commonly use.
3. No Egyptian identifier could be checked: tax registration number, national ID, commercial
   register number, phone numbers, postal codes.
4. Arabic in PDFs was shaped but never mirrored: tables kept their left-to-right column order,
   and Urdu text could not be bold because the only face that draws it had one weight.

Everything below is country-neutral. Egypt is the first set of data rows, not a code path.

## Decisions

**D1. Digit system is its own preference, orthogonal to the number format.** A new user
preference `digitSystem` with values `auto | latn | arab | arabext`. `auto` keeps what the
locale already does. Any other value is applied as the BCP-47 Unicode extension `-u-nu-<system>`
to the resolved tag, in the two resolvers that already answer "which locale": `getIntlLocale()`
(dates, lists) and `resolveNumberLocale()` (numbers, money). No new formatter. The extension is
skipped when the locale already uses that system, so `en` stays `en`. Persian (`arabext`) and
any other script can use the same switch.

**D2. `ar-EG` is offered as a number format.** It joins `NUMBER_LOCALES`, so an Egyptian reader
can pick Egyptian conventions explicitly. The `ar` language mapping (`ar` to `ar-SA`) is left
alone: changing it would move every Gulf reader.

**D3. The account stores the digit choice in `users.metadata["digit_system"]`.** No migration.
`GET/PATCH /v1/users/me/preferences/` gain an optional `digit_system` field validated against
the same allow-list.

**D4. Documents: the market decides, an explicit reader choice overrides.** `COUNTRY_DEFAULTS`
rows may carry `digit_system`. `regional_format.number_style()` reads it, so all nine generators
that already print through `number_style()` follow without a call-site change. A request may
override it: the frontend sends `X-Digit-System` when the reader chose a system explicitly, and
`?digits=` works on any URL. The existing `AcceptLanguageMiddleware` reads both into a context
variable, the same way it already sets the request locale. Separators follow the digits: Arabic-
Indic digits print with `٬` and `٫` (CLDR `arab` symbols), Western digits with the country's own
separators. Egypt's row says `latn` (business documents), so an Egyptian PDF prints `1,234.56`
unless the reader asked for Arabic-Indic digits.

There is no organisation-level regional settings table in the product today. The organisation
level is therefore the country data row (shipped, selected by the project's country and by the
pack). A tenant-editable override needs a table and is left for later; recorded here, not built.

**D5. Identifiers live in one country-neutral catalogue with sources.**
`app/core/validation/identifiers.py` holds rows keyed by `(country, kind)` with a pattern, an
optional structure spec, the source, its URL, the effective date, a confidence and a
`needs_expert_review` flag, and one validator `validate_identifier(country, kind, value)`.
Kinds: `tax_registration`, `national_id`, `company_register`. The subcontractor tax-ID check
consults this catalogue for a country its own table does not have, so the Egyptian RIN has
exactly one home. Phone and postcode rows go into the existing `phone.py` and `address.py`
registries with source fields on the row. All validators read Arabic-Indic and Persian digits
as digits (`٠١٢` is `012`), because an Arabic keyboard types them.

**D6. Unconfirmed facts never become hard rules.** Every Egyptian row is
`needs_expert_review=True` because no primary regulator text giving the format was reachable.
The national ID check verifies length, century digit, a real birth date and a governorate code
from the shipped list; it does not verify the final check digit, whose algorithm is not
published. The commercial register number has no national format, so the row accepts 1 to 10
digits and says so.

**D7. RTL tables are mirrored at construction, not per generator.** `pdf_rtl` gains a
`table_direction(direction)` context. While it says `rtl`, a reportlab `Table` built in it
reverses each row, its column widths and its style commands (columns renumbered, `LEFT` and
`RIGHT` swapped, `LINEBEFORE` and `LINEAFTER` swapped), with a right-aligned base. Tables that
reportlab rebuilds when splitting across pages (`normalizedData=1`) are not mirrored again.
The shared form and register renderers (`register_export._build_twice`) enter the context from
the document title's own direction, so every form whose catalogue ships an RTL language
(finance, procurement: ar, ur, fa, he) is mirrored with no change in the module. Shaping is
untouched (founder question AM-Q3 stays open on that point only).

**D8. Bold Arabic-script face.** `NotoNaskhArabic-Bold.ttf` (unhinted, SIL OFL 1.1, from the
same Noto release as the shipped Regular; the Regular in the repo is byte-identical to that
release, SHA-256 `c34fdbd9...b221`) is registered as the bold member of the family, and the
font ladder offers it to bold text. Hebrew already draws in DejaVu Sans Bold.

## Data and sources

| Row | Value | Source | Confidence |
|---|---|---|---|
| `COUNTRY_DEFAULTS["EG"]` | EGP, metric, A4, `DD/MM/YYYY`, `1,234.56`, `ar`, digits `latn` | CLDR `ar-EG`; Western digits per common business practice (eg_research) | M |
| RIN (`tax_registration`) | 9 digits, printed `123-456-789` | ETA SDK names the field (https://sdk.invoicing.eta.gov.eg/documents/invoice-v1-0/) but gives no length; length from secondary sources | M, needs review |
| National ID | 14 digits: century (2 = 1900s, 3 = 2000s), YYMMDD, governorate (27 codes + 88 abroad), serial, gender digit 13, check digit | Secondary (https://en.wikipedia.org/wiki/Egyptian_National_Identity_Card); check-digit algorithm unpublished | M, needs review |
| Commercial register | no national format; 1 to 10 digits accepted | Law 34/1976 sets registers per office (https://alp.unescwa.org/legislations/law-34-1976-commercial-registry) | L, needs review |
| Phone | +20; mobile 10, 11, 12, 15 + 8 digits; Cairo/Giza 2 + 8; other areas 7-digit subscriber | https://en.wikipedia.org/wiki/Telephone_numbers_in_Egypt (secondary) | M, needs review |
| Postcode | 5 digits, or 7 digits per the UPU sheet of 07/2023 | https://www.upu.int/UPU/media/upu/PostalEntitiesFiles/addressingUnit/egyEn.pdf | M, needs review |

## Test plan (distinguishing cases)

Backend (`backend/tests/unit/`):

- `test_documents_write_digits_their_market_or_reader_chose.py`: EG prints `1,234,567.89`;
  with digits `arab` the same amount prints `١٬٢٣٤٬٥٦٧٫٨٩`; a German style with digits `arab`
  keeps Arabic-Indic separators, not `.` and `,`; a country row with no `digit_system` is
  unchanged byte for byte; dates follow the digit system; the middleware sets and clears the
  context per request (a second request without the header is Western again).
- `test_identifiers_are_checked_against_sourced_rows.py`: a valid national ID passes and reports
  birth date, governorate and sex; century `4`, month `13`, governorate `20` fail with distinct
  reasons; an ID written in Arabic-Indic digits passes; the RIN with dashes passes, 8 digits
  fail; every EG row carries a source URL, an effective date and `needs_expert_review`;
  `validate_tax_id("EG", ...)` answers with the RIN standard; Egyptian mobile `010...`,
  `+20 11...` pass and `013` mobile-length fails; a 5-digit and a 7-digit postcode pass.
- `test_rtl_tables_mirror_and_arabic_bolds.py`: a table built inside `table_direction("rtl")`
  has its first column drawn rightmost (x positions read back from the PDF with pdfplumber);
  `SPAN`, `ALIGN`, `LINEBEFORE` and negative indexes are mirrored; a long table split over two
  pages is mirrored exactly once on both pages; outside the context nothing moves; an Arabic
  finance invoice renders its line-item header right to left and its bold Urdu text embeds
  `NotoNaskhArabic-Bold`.

Frontend (`vitest`):

- `digitSystemReachesEveryFormatter.test.ts`: with `digitSystem = 'latn'` an Arabic UI formats
  money and dates with Western digits; with `'arab'` an English UI formats them with Arabic-Indic
  digits; `'auto'` leaves `getIntlLocale() === 'en'` untouched; the server value is adopted only
  when it is in the allow-list; `ar-EG` is offered.

## Left open

- Tenant-editable digit system per organisation (needs a table).
- Founder AM-Q3 (letter shaping approach and the LGPL licence of python-bidi): untouched.
- An Egyptian expert should confirm every row flagged `needs_expert_review`, the national ID
  check-digit algorithm in particular.
