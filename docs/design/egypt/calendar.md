# Egypt: working week, public holidays and labour standards

Stream `calendar` of the Egypt programme. Branch `wip/eg-calendar-20261019`.

## Problem

Before this change an Egyptian project was planned on the Monday to Friday
`DEFAULT` week with no public holidays. Fridays counted as working days, Sundays
as rest days, and no Egyptian holiday existed anywhere: not in
`core.calendar._WORKING_WEEK`, not in `_HOLIDAY_FUNCS`, not in the schedule's
`WORK_CALENDARS`, not in the seeded `work_calendars.json`. The coverage
instrument reported EG as missing or fallback on all four calendar registries.
The middle-east pack carried a correct `work_week` key that nothing reads.

## Scope

1. Working week Sunday to Thursday, Friday and Saturday off, in every registry a
   date is computed from.
2. Egyptian public holidays as the engine computes them, plus the per-year
   observed-date moves the government announces, held as data.
3. Statutory labour facts (hours, leave, minimum wage, social insurance general
   rates) as effective-dated, sourced data, and EGP labour-rate templates
   derived from them.

Out of scope, recorded so nobody reads silence as coverage: public-sector Eid
extensions (cabinet adds days for the civil service only), Ramadan reduced
hours (no private-sector legal basis found), the contracting social-insurance
mechanism (Table 8 wage percentages, UNCONFIRMED), and the `middle_east_pack`
clean-up of its dead keys (another stream).

## Decisions

**Week.** Labour Law 14/2025 caps work at 8 hours a day and 48 a week and gives
at least 24 consecutive hours of paid weekly rest, Friday by custom. No statute
names Saturday. Sunday to Thursday at 8 hours is the government week and the
common private-sector office week, and it is what the lead specified. A site
that works Saturday to Thursday (six days, common on Egyptian construction
sites) sets its own calendar, the same stance the Turkish and Spanish entries
take. The schedule gets its own `EGYPT` calendar rather than reusing `GULF`,
so the badge an Egyptian project shows does not read "Gulf".

**Holiday roster.** Ministerial Decree 294/2025, issued under Labour Law
14/2025, lists the paid holidays: Hijri New Year (1 Muharram), the Prophet's
Birthday (12 Rabi al-Awwal), Eid al-Fitr (1 and 2 Shawwal), Arafat Day and the
first two days of Eid al-Adha (9, 10 and 11 Dhu al-Hijjah), Coptic Christmas
(7 January), 25 January, Sham el-Nessim, 25 April, 1 May, 30 June, 23 July and
6 October. Fifteen days a year before moves.

**Computed, country-neutral pieces.** `orthodox_easter(year)` (Julian computus
expressed in Gregorian dates, via `dateutil`'s Orthodox method, tested against
published dates), `julian_christmas(year)` (25 December Julian in Gregorian
terms: 7 January from 1901 to 2100, 8 January from 2101) and
`_hijri_span(month, day, length, year)` (a run of consecutive days from a fixed
Hijri date). Sham el-Nessim is the Monday after Orthodox Easter. Islamic dates
come from the same `hijridate` converter the Gulf uses. `_gcc_eids` is left
untouched, so no Gulf date can move.

**Observed-date moves are data, never a computed guess.** Decree 294/2025 lets
the Labour Minister replace a holiday with a day at the start or end of the
working week, and since 2020 the Prime Minister moves most midweek national
days to Thursday by decree each time. Whether a given holiday moves in a given
year is a decision, so nothing computes it. Each announced move is a row in
`backend/app/core/country_data/holiday_observances.json`, keyed by country, year
and holiday, carrying the dates the engine computes, the dates actually
observed, the authority, a source URL and whether the source states it covers
the private sector. The same rows correct a lunar date when the official moon
sighting differs from the converter. A row whose `statutory` dates no longer
match what the engine computes makes the whole year raise
`HolidayCalculationError` rather than apply a move to the wrong day. One loader
validates every row for every country.

**Years before the decree.** Decree 294/2025 took effect with the Labour Law on
2025-09-01. A year starting before that is answered with the 294/2025 roster
and reported as a fallback on the `effective_year` axis
(`ROSTER_FROM_LATER_DECREE`), because the earlier roster under Law 12/2003 is
not modelled.

**Labour facts.** No per-country statutory labour registry existed (payroll
holds a single global overtime multiplier). A small country-neutral catalogue
is added, `backend/app/core/country_data/labour_standards.json` with the loader
`app/core/labour_standards.py`, rather than scattering numbers into seeds.
Every row carries value, unit, effective window, source, URL, confidence and
`needs_expert_review`. Rows flagged for review are returned by the loader but
refused by `hard_standard()`, the accessor a rule must use, so an UNCONFIRMED
fact can be shown and edited but cannot be enforced. The EGP labour-rate
templates read their minimum wage, social insurance rate and leave days from
this catalogue, so the numbers live once.

**Labour-rate regions.** `LaborRateTemplate` has no region or country column,
and adding one needs a migration, an API change and a UI. Not done here: the
EGP templates are named for Egypt the way the Gulf template is named for the
Gulf. The coverage instrument keeps reporting `labour.rate_regions` as
not-keyed, which is the truth.

## Data sources

| Fact | Value | Source | Effective | Conf. |
|---|---|---|---|---|
| Holiday roster | 15 days listed above | Ministerial Decree 294/2025; Al Tamimi summary https://www.mondaq.com/employee-rights-labour-relations/1733268/ ; repository copy https://dspace.id.com.eg/items/f66386dd-dcb6-4ba9-b231-23f3f5a0c68f/full | 2025-09-01 | M |
| 2025 move 30 Jun to 3 Jul | | PM Decree 2130/2025 https://erp.id.com.eg/vufind/Record/oai:dspace.id.com.eg:123456789-3853/Description | 2025 | M |
| 2025 move 6 Oct to 9 Oct | | https://www.cairo.gov.eg/en/news/news-eng/2025/4b6012afdea54aac811e086ee5b4e0ad | 2025 | M |
| 2026 move 25 Jan to 29 Jan | | PM Decree 199/2026 https://dspace.id.com.eg/items/8e5d209a-b3f0-47b4-b904-edb81c6e4823/full | 2026 | M |
| 2026 Hijri New Year on 18 Jun | | https://www.cairo.gov.eg/en/news/2026/june/9_june/de4fb420b9864472ae90cbef4d019f05 | 2026 | M |
| 2026 move 30 Jun to 2 Jul | | https://www.cairo.gov.eg/en/news/2026/june/24/30_june/ | 2026 | M |
| 2026 Prophet's Birthday on 27 Aug | | https://arabfinance.com/en/news/newdetails/madbouly-declares-august-27-as-official-holiday-for-prophet-muhammad-birthday | 2026 | M |
| 2026 move 6 Oct to 8 Oct | | https://arabfinance.com/en/news/newdetails/madbouly-declares-october-8-public-holiday-for-armed-forces-day | 2026 | M |
| Hours | 8/day, 48/week | Labour Law 14/2025 via https://www.mondaq.com/employee-rights-labour-relations/1791586/ | 2025-09-01 | M |
| Overtime premium | 35% day, 70% night | Ministry of Labour explanation via https://www.masrawy.com/news/news_egypt/details/2026/9/4/3043032 ; one transcription of the law (Art. 122) reads 25% by day; article number not found | 2025-09-01 | configurable default, flagged for review |
| Holiday work | double pay on top of the day's wage, or a compensatory day on written request | Decree 294/2025 via Al Tamimi | 2025-09-01 | M, shipped as review data: 2x or 3x in total is unclear |
| Annual leave | 15 first year, 21 after, 30 after 10 years or age 50, 45 with disability | Labour Law 14/2025, EY and Clyde & Co | 2025-09-01 | H |
| Emergency leave | 7 days a year | Clyde & Co | 2025-09-01 | M |
| Maternity leave | 120 days | EY, Clyde & Co | 2025-09-01 | H |
| Minimum wage, private sector | EGP 7,000 a month | National Wages Council via https://moic.gov.eg/news/1998 | 2025-03-01 | H |
| Annual increment | at least 3% of insurable wage, at least EGP 250 | EY; moic.gov.eg | 2025-09-01 | H |
| Social insurance, general | employer 18.75%, employee 11% | Law 148/2019, PwC | 2020-01-01 | H |

Also left out on purpose: an end-of-service gratuity (Law 14/2025 Art. 172 grants
one only where social insurance does not apply, or on wage outside the insurable
wage, so there is no general rate to ship) and the seven-working-day settlement
of final dues (Art. 171), which has no verified source URL yet. No statutory
private-sector Ramadan reduction exists, so none is encoded; a company that
shortens Ramadan hours does it on its own calendar.

**Per-country Eid spans.** `_gcc_eids` used to apply one placeholder span
(three days of Eid al-Fitr, four of Eid al-Adha from 10 Dhu al-Hijjah) to all
six Gulf states. The span is now a row per country in `_EID_SPANS`. Saudi
Arabia gets its sourced row (Labour Law Implementing Regulations Art. 24: four
days of Eid al-Fitr from 1 Shawwal, four of Eid al-Adha from the Day of Arafah)
and an observance row for the 2026 Eid al-Fitr HRSD announced from 19 March,
so the engine now equals the shipped 2026 Saudi calendar. Egypt gets the Decree
294/2025 row. The UAE, Qatar, Kuwait, Bahrain and Oman keep the placeholder
unchanged, because no source was checked for them, and still report it on the
extent axis. One computational fix reaches all of them: an Eid that starts in
late December now files its January days under the next year (the only case in
the converter's window after 2006 is Eid al-Adha 2071/2072).

The 2025 move of 23 July to 24 July is reported only by a schedule note and is
not recorded. Moves before 2025-09 are not recorded either.

## Consumers checked

`core.calendar.is_working_day` / `add_working_days` read `_WORKING_WEEK` and
`_HOLIDAY_FUNCS`. The schedule (`compute_duration`, BOQ schedule generation,
XER and MSP imports, the progress forecast, permits, staffing hours) reads
`get_work_calendar`, which now resolves `EG`, `EG_CAIRO`, `Egypt` and a project
whose country column says EG. A typed country name ("Egypt") reaches the
week through the label table but not the holidays, because the region registry
resolves no country names for any country ("Qatar" behaves the same); the
project's country column closes that. The i18n-foundation working-day endpoint reads
the seeded calendar rows, and the EG 2026 row is delivered to existing installs
through `CALENDAR_FIRST_SHIPPED`.

Not fixed here, because they ignore every country and changing them changes
dates for all of them: `contracts.intl._apply_weekend_rule` (payment due dates
roll off Saturday and Sunday only), `rfi.service._add_business_days` (Monday to
Friday response clocks) and the demo seeds in `field_time`, `value` and
`daily_diary`, which generate Monday-to-Friday history. These are recorded as
open items for the lead.

## Test plan (distinguishing cases)

- Orthodox Easter for 2021 to 2027 against published dates, including 2024 and
  2027 where it falls five weeks after Western Easter and 2025 where both agree.
- Julian Christmas is 7 January in 2026 and 8 January in 2101.
- The 2025 and 2026 EG holiday sets, written out by hand.
- A schedule spanning a Friday, a Saturday and Sham el-Nessim counts Sunday to
  Thursday minus the holiday, and the same span under Monday to Friday gives a
  different number (the case that fails on the old fallback).
- A move row whose statutory date does not match the engine raises.
- 2027, with no rows, answers the statutory days, and 2024 reports the
  pre-decree fallback.
- GCC: the 2025 and 2026 holiday sets and weeks of SA, AE, QA, KW, BH and OM are
  pinned before and after.
- Labour: every row validates; review-flagged rows are refused by
  `hard_standard`; the EGP templates pay at least the minimum wage per hour and
  carry the catalogue's social insurance rate.
