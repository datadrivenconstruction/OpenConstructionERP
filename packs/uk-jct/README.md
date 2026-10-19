# UK Construction Pack

Pre-configures OpenConstructionERP for United Kingdom contracting: the RICS
measurement rules, the JCT contract suite, the Construction Act payment
regime, CIS and the VAT domestic reverse charge, CDM 2015 duties and the
Building Safety Act 2022.

## What this pack enables

- Currency GBP (the pack does not set VAT) and the `united_kingdom`
  estimating methodology
- The en-GB locale overlay
- Two engine rule sets: `nrm`, the method of measurement, and `uk_statutory`,
  the law of one country
- Nine reference documents: `nrm_1_cost_planning`, `nrm_2_detailed_measurement`,
  `nrm_3_maintenance`, `jct_contract_suite`, `construction_act_payments`,
  `uk_tax_and_cis`, `cost_benchmarking`, `cdm_2015` and `bsa_2022`
- The `cwicr-uk-gbp` cost region, which loads on demand
- A six-step onboarding wizard that collects exactly what the statutory
  checks read back, so those checks can be cleared rather than carried

## What the checks actually check

The `nrm` set asks whether the cost plan is a cost plan. Every item
classified, the code well formed, the major groups present, the base date and
the stage stated, and the money that is never measured actually in it: the
main contractor's preliminaries, its overheads and profit, the risk
allowance. Those last three are the ones a plan omits silently, and a cost
per square metre computed without them is a number nobody can build to.

The `uk_statutory` set asks what the estimate records about itself: the
contract form it is priced against, the payment dates, the retention, the CDM
appointments, the VAT treatment. All of those are presence checks, on
purpose. Percentages, notice periods and retention rates are commercial terms
this platform has no basis to assert, so it does not assert them.

One check is different. The higher-risk building test is statute, so it is
checked rather than described: a building is higher risk when it is at least
18 m tall or has at least 7 storeys **and** contains at least two residential
units, with care homes and hospitals also in scope during design and
construction. Both halves count. A ten-storey speculative office with no
dwellings in it is outside the regime however tall it is, and the rule reads
the storeys, the height and the dwelling count back against the answer the
estimate gave. Getting this wrong in the generous direction buys months of
gateway programme nobody needed; getting it wrong the other way stops the
building being occupied.

## The rule ids are honest now

This pack used to declare 97 rule ids across its documents. None of them
existed. A document that promises a check tells an estimator the platform is
watching something it is not, which is worse than the check being absent,
because an absent check at least does not claim otherwise. Every id declared
today resolves to a rule in the engine, and the documents that enable nothing
say so and say why.

## Which modules a UK contractor needs

The pack hides nothing, so every module is visible. These are the ones that
carry UK-specific behaviour, and it is worth naming them because two of them
already do the work this pack was previously describing in prose.

- **Payment Clock** (`oe_payment_clock`) holds the statutory payment regime.
  It carries the UK entry with the Construction Act dates, computes the due
  date, the notice deadlines and the final date for payment, records the
  notices actually served, and reports the consequence when a deadline passes
  unanswered. This is the module a UK contractor gets the most out of and the
  pack never used to mention it.
- **Withholding Tax** (`oe_tax_withholding`) carries the CIS scheme and the
  VAT domestic reverse charge rule for construction. Deduction rates,
  verification and the materials exclusion live here rather than in the
  estimate.
- **Cost-Value Reconciliation** (`oe_cvr`) is the monthly reconciliation a UK
  commercial team runs, and the concept is close to universal in British
  practice and rare elsewhere.
- **Preliminaries** (`oe_preliminaries`) prices the site as its own section,
  which is what NRM 2 asks for and what a bill that spreads preliminaries into
  rates cannot be checked against.
- **Variations**, **Defects Liability** and **Closeout** carry the rest of the
  contract lifecycle a JCT job runs through.

What is not there yet, stated rather than implied:

- No construction phase plan or health and safety file document type. CDM 2015
  requires the first on every project and the second wherever more than one
  contractor works, and this pack checks that the appointments are recorded
  but has nowhere to keep the documents themselves.
- No golden thread register. The Building Safety Act expects the information
  about a higher-risk building to be kept accurate, current and accessible
  through handover, and that is a deliverable with a cost and an owner.
- No CITB levy assessment. It falls on payroll rather than on a project, so it
  belongs in the company overhead, and nothing computes it.

## Cost data

**No commercial cost database is bundled.** The UK unit-price and benchmark
datasets sold by subscription are licensed products, and redistributing one
inside an AGPL pack is not something their terms allow.

The `cost_benchmarking` document holds the method rather than the data: what
has to match before a comparison means anything, and how to record a benchmark
so somebody else can re-check it. Bring your own rates, from your cost
history, a subscription you hold or a published schedule.

## The United Kingdom is four jurisdictions

Worth stating because the pack is one and the country is not. The Building
Safety Act gateway regime and the reformed building control regime are England
only. CDM 2015 covers Great Britain, and Northern Ireland has its own
regulations to similar effect. The Construction Act applies across Great
Britain, and Northern Ireland has its own order to the same effect. Contracts
performed in Scotland are governed by Scots law, and the JCT forms are used
there with Scottish supplements.

## Standards referenced

- RICS NRM 1, NRM 2 and NRM 3. Cite the edition you hold in the project
  record: the group numbering the validator uses is stable across editions,
  and the commentary is not.
- JCT standard forms of building contract
- Housing Grants, Construction and Regeneration Act 1996, as amended by the
  Local Democracy, Economic Development and Construction Act 2009, and the
  Scheme for Construction Contracts
- Construction Industry Scheme, and the VAT domestic reverse charge for
  building and construction services
- Construction (Design and Management) Regulations 2015
- Building Safety Act 2022 and the regulations made under it

These are referenced for interoperability and compliance checking. Clause and
section numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here. Nothing in this pack
is legal or tax advice, and the review status recorded on each document says
who has and has not read it.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "UK Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=uk-jct openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
