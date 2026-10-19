# India Construction Pack

A country pack for Indian work. It configures the workspace the way an Indian
estimate is actually built: against a published schedule of rates, measured to
IS 1200, priced in rupees, with GST and the withholdings that come off a
contractor's payment rather than out of the estimate.

## What makes an Indian estimate Indian

An estimate here is written against a schedule of rates, and which schedule
depends on who is paying. CPWD publishes the Delhi Schedule of Rates for
central government work. Every state PWD publishes its own for state work, and
they are not interchangeable: the item numbering differs, the specifications
differ, and a rate lifted from the wrong schedule is not an approximation, it
is the wrong number. The pack ships the CPWD documents and names the state
schedules rather than pretending one covers the other.

Measurement is its own standard. IS 1200 says how a quantity is arrived at,
part by part, and a BOQ that measures otherwise cannot be checked against a
schedule that assumes it. Metric only, and the unit vocabulary is small and
fixed.

Three deductions sit between the certified value and the money that arrives,
and none of them is a cost in the estimate. GST at the applicable rate, TDS
under section 194C, and the BOCW labour cess. They change the invoice and the
working capital, not the price of the work, and putting any of them into a
rate is the most common way an Indian estimate ends up wrong.

## What this pack enables

- **Currency INR** (the pack does not set GST) and the `india` estimating
  methodology, with an English and Hindi interface.
- **Two engine rules**, under the `cpwd` rule set. `cpwd.code_required` asks
  that every priced line carries a schedule item reference, because a rate
  with no item behind it is a number a client cannot check. `cpwd.measurement_units`
  asks that the unit is one IS 1200 recognises, and it is metric only.
- **Eight reference documents** covering CPWD Specifications 2019 and the
  Works Manual, DSR 2023, IS 456, IS 800, the IS 1893 / IS 875 / IS 13920
  seismic bundle, NBC 2016 with the 2024 amendments, RERA 2016, and the tax
  and statutory set. These are reference material for the estimator, not
  executable checks; the two rules above are what the engine runs.
- **A seven-step onboarding wizard** that collects the work type, the
  specification, the rate schedule, the tax position and the statutory
  registrations, in English and Hindi.
- **A demo project**, `govt-building-delhi`: a six-storey central government
  office block at Lodhi Road, 97 priced items across 13 sub-heads from
  earthwork to external services, on DSR rates at a Delhi price level, with
  the four markups an Indian tender carries: contractor's profit and
  overheads, contingencies, the labour cess and GST. It passes both `cpwd`
  rules with nothing outstanding, and its validation dashboard opens at 97.8
  percent with quality warnings and no errors, which is what every demo in the
  product looks like.

## Cost data

**No commercial rate schedule is bundled.** DSR and the state schedules are
published documents with their own terms, and redistributing one inside an
AGPL pack is not something those terms allow.

One Indian catalogue loads on demand, `cwicr-hi-mumbai`. Delhi, Bangalore,
Chennai, Hyderabad, Kolkata and Pune are recorded in the manifest as planned
and no catalogue is published for them yet. That matters more here than
elsewhere, because DSR is a Delhi schedule: for Delhi work the rates come from
your own cost history or your own copy of the schedule, not from this pack.

The manifest used to declare all seven as if they loaded. Six of them resolved
to nothing and were skipped at install without an error, so the pack read as
though it shipped seven cities of rates and shipped one.

## CPWD is central, and India is not

Worth stating plainly because the pack is named after one authority. CPWD
Specifications, the Works Manual and DSR govern central government works.
State PWD works follow the state's own schedule of rates and its own
specifications, and the onboarding wizard asks which one you work to so the
right reference is loaded. The IS codes and NBC apply regardless; RERA applies
to registered real estate projects and is administered state by state.

The manifest records the state schedules the pack is designed to sit alongside
under `compatible_state_sors`. It does not ship them.

## Standards referenced

- CPWD Specifications 2019, volumes I and II, and CPWD Works Manual 2019
- CPWD Delhi Schedule of Rates 2023
- IS 456:2000, plain and reinforced concrete
- IS 800:2007, general construction in steel
- IS 1893 part 1:2016, IS 875 parts 1 to 5:1987, IS 13920:2016
- IS 1200, method of measurement of building and civil engineering works
- National Building Code of India 2016, with the 2024 amendments
- Real Estate (Regulation and Development) Act 2016
- CGST, SGST and IGST Acts; Income Tax Act section 194C; Building and Other
  Construction Workers Welfare Cess Act 1996

These are referenced for interoperability and compliance checking. Clause,
section and item numbers are interoperability facts and are used as such; the
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The item references, units and structure of the demo estimate follow the
published CPWD sub-head order and IS 1200 units. The statutory and tax
references are drawn from public sources and are pending review by an Indian
quantity surveyor before they are relied on for a government tender. Each
rule-pack document now carries a `review_status` saying what kind of claim it
is and who has not read it. The two engine rules are the only parts of this
pack that assert anything about an estimate; the documents are there to be
read.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "India Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=india-cpwd openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
