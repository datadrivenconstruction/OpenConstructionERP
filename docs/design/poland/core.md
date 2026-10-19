# Poland core: late payment, VAT checks

Status: implemented, Polish figures carry a review status and sources in the data files.

## One late payment engine, in two layers

`app/modules/payment_clock` answers "which day is the final date" (notice regimes, pay-less notices).
`app/core/late_payment.py` answers "what is owed after that day": dated statutory interest, the longest
payment term a statute allows per debtor kind, and fixed recovery compensation tiers. They do not overlap.
The payment_clock regime row for a country only describes the interest basis in words; the dated figures
live in `app/core/country_data/late_payment.json`, and a unit test ties the margin in both together.

`late_payment.py` is country neutral. A country is one row under `countries` with the statute, its source,
a reference rate and the day it is fixed, a margin per debtor kind, the reference rate per dated period,
term caps and compensation tiers, each with source, effective dates and confidence. A day outside every
listed period has no known rate and the engine says so. France and any other country add a row; no code
change. Poland is the first row.

## VAT

Polish rates (23, 8, 0) are canonical in `app/core/tax.py` and the dated tax seed. `vat_construction.json`
holds no rate: it names a tax code and reads the rate from the seed. The split payment threshold and the
housing area limits are canonical in `vat_construction.json`; the KSeF work reads them from there.
