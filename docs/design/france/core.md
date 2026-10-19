# France: late payment (engine row)

The French row of `backend/app/core/late_payment.py` prices commercial debtors per
half-year (Code de commerce L441-10 II, ECB rate plus 10 points) and public buyers with
`rate_fixing: at_delay_start` (Code de la commande publique R2192-31: ECB rate in force on
the first day of the half-year in which the delay started, plus 8 points, held for the whole
delay). `rate_fixing` is a country-neutral margin field, default `per_period`.

The agreed-rate floor (three times the legal interest rate, L441-10 II) is data
(`agreed_rate_floor`, `legal_interest_rates`) read by `agreed_rate_floor_percent`.

## Open

- 45 days end of month as the alternative term cap (L441-10 I al. 2): `term_caps` holds only
  `max_days`; end-of-month arithmetic is not expressed. The 60 day cap is enforced, the
  alternative is not.
- Legal interest rates exist only for 2026; the H1 2026 figure (2.62) is one secondary source.
- The ECB 2.40 figure for H2 2026 is a single secondary source (FNTP); the whole FR row stays
  `needs_expert_review`.
- Public medical establishments and public undertakings: margin not shipped, only the term caps.
