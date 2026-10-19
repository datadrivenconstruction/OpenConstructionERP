# France, labour stream: labour figures

Labour facts are rows of the country-neutral labour standards catalogue
(`app/core/country_data/labour_standards.json`), not a second store: 35 h legal week (L3121-27),
default overtime +25 / +50 (L3121-36), 11 public holidays, SMIC EUR 12.02/h and EUR 1,823.03/month
from 2026-01-01, CIBTP paid-leave fund 20.20 % (Ile-de-France), bad-weather fund 0.68 % structural and
0.13 % finishing works for the campaign 2026-04-01 to 2027-03-31, OPPBTP levy 0.11 % for 2026.

Flagged `needs_expert_review` (shown, never enforced): the SMIC rows, because a revision later in 2026
was not confirmed, and the CIBTP paid-leave rate, because it differs by caisse and the catalogue has no
region key yet.

Left out with a reason: the BTP annual overtime quota (sources give 180, 265 or 300 hours) and the
bad-weather indemnity mechanics (not read).
