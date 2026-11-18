# Texas Construction Pack

State depth for Texas, layered on top of the US Construction Pack rather than
repeating it. The national pack already carries the classification structures,
the owner-contractor agreement family, the progress payment application and
imperial units. This pack carries the four things that change when a job is in
Texas and that an estimator working from national defaults gets wrong.

## What this pack carries

### Sales tax, and who owes it on materials

Texas is 6.25 percent at state level with up to 2 percent of local tax stacked
on, so 8.25 percent is the ceiling. The rate is the easy part. The part that
moves money is which of you owes it:

- **Lump sum contract, new construction.** The contractor is the consumer of
  the materials. It pays tax to its supplier and charges the customer no tax at
  all. The tax is a cost inside the bid.
- **Separated contract, new construction.** The price is split into at least a
  materials charge and a labor charge. The contractor is now the seller of the
  materials: it buys them tax free for resale and collects tax from the
  customer on the materials charge. Labor to build new real property is not
  taxable.
- **Repair, remodeling or restoration of nonresidential property.** This
  reverses the rule. The total charge is taxable, labor included. An office or
  retail fit-out that is a repair rather than new construction carries tax on
  the whole invoice.
- **The same work on residential property.** Labor is not taxable and the
  contractor is the consumer of the materials.

Two contracts for the same scope at the same price can therefore carry
different tax, which is the point of pricing the choice rather than inheriting
it.

### Prevailing wage

Texas has no state wage schedule and no state body that publishes one. The
public body awarding the contract determines the rate itself, either by
surveying wages on similar projects in its own political subdivision or by
adopting the federal determination for the locality. Two Texas cities can carry
different rates for the same craft in the same month, so the rate has to be
read out of the awarding body's documents. There is no minimum contract value:
the duty attaches to public work paid for wholly or partly from public funds.
Underpayment costs 60 dollars per worker per calendar day.

### Retainage on public work

One threshold does the work. Below a 5 million dollar contract price the cap is
10 percent; at or above it the cap falls to 5 percent. Dam work stays at 10
percent whatever the price. Retainage above 5 percent of the periodic payments
has to sit in an interest-bearing account. None of this reaches a contract
estimated under 400 thousand dollars at execution, or state transportation
department contracts.

### Payment and lien clocks

- Public work: the governmental entity's payment is overdue on the 31st day,
  so 30 days to pay, and 46 days where the governing body meets monthly or
  less. Interest is one percent over the prime rate, fixed annually on
  1 September. The prime must pass a subcontractor's share on by the 10th day.
- Private work: the owner pays by the 35th day after receiving the written
  payment request, the contractor pays its subcontractor by the 7th day after
  being paid, and unpaid amounts run at one and a half percent a month. The
  chapter cannot be waived, with a narrow single-family residential exception.
- Lien: the affidavit is due on the 15th day of the third month after the month
  the work ended for residential and the fourth month for nonresidential, which
  is a day of a month rather than a count of days. Suit to foreclose follows
  within a year of that last day, extendable to two by recorded agreement.

### Statutory checks, worked

The statutory engines compute the Texas tables for one project and turn them
into findings (document `tx_statutory_checks`). Worked examples, 8.25 percent
combined rate:

- Lump sum, 500,000 dollars of materials: the contractor pays 41,250 at
  purchase and charges no tax. A separated contract pricing the same materials
  at 550,000 charges the owner 45,375.
- A subcontractor unpaid for May 2026 work on a nonresidential job sends its
  notice of claim by 15 August 2026 (Property Code § 53.056(a-1)(1)); the
  finding turns into an error the next day.
- The original contractor's lien affidavit after completion on 20 October 2026
  is due on 15 February 2027, and suit by 15 February 2028.
- The owner of a 1.2 million dollar private contract holds 120,000 as the
  statutory reserve for 30 days after completion (§ 53.101).

### No state income tax

The Texas constitution prohibits a tax on individual net income outright, so a
Texas labor burden carries no state withholding line.

## Contractor licensing

Texas issues no state general-contractor licence. Electrical, plumbing and HVAC
are licensed at state level, and general contracting is licensed by the city
where it is licensed at all. A Texas bid has to name the municipality before
the licensing position can be answered.

## Where the numbers live

Every figure above is served by the `oe_us_tx_pack` backend module at
`/api/v1/us-tx-pack/rules/`, and every rule there carries the statute it comes
from. Nothing in this pack states a rule without a citation. The statutory
payment periods are also seeded into the payment clock as the regimes
`us_tx_public_2251` and `us_tx_private_ch28`, so the clock computes real dates
rather than describing them.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Packs: click Rescan, find "Texas Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=us-texas openconstructionerp serve
```

## What this pack is not

It bundles no cost data and no wage rates. Texas prevailing wage rates are set
per awarding body and cannot be shipped as a national table; the pack tells you
where the rate comes from, and you import the one your contract names.

The figures are current as at the pack version and every one names its statute
so it can be checked. They are a working reference, not legal advice, and a
project of any size should confirm the position with its own counsel.

## Open items

- Senate Bill 1530 (89th Legislature) is not reflected. No figure from it ships
  until it is read against the enrolled text and the amended sections of
  Property Code Chapter 53.
