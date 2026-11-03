# Estimating and the bill of quantities

The bill of quantities is the heart of the platform. It is where measured work becomes priced work, and where an estimate takes shape from a first rough number to a document you can put in front of a client or a tender board.

## What it is for

A BOQ is a structured, hierarchical list of the work in a project: sections, positions and sub-positions, each with a description, a unit, a quantity and a unit rate. The platform multiplies quantity by rate for each line, rolls up section subtotals, applies your markups, and gives you a live grand total. The same structure carries classification codes, links back to the drawings or model elements a quantity came from, and a validation status, so an estimate is never just a spreadsheet of numbers with no provenance.

## When to use it

Reach for the BOQ editor as soon as you have any scope to price, whether the quantities come from a takeoff, a BIM model, an import, or your own judgement. If you are still at the earliest stage and only have a floor area or a unit count, start with a conceptual, order-of-magnitude estimate and let it grow into a full BOQ later.

## The steps

1. Create a project and open its BOQ. A project carries the region, currency and classification standard that the estimate will use, so set those first.
2. Add sections to match your trade or cost-group structure, then add positions under them. You can type them in, paste from a spreadsheet, or generate them from a takeoff, a matched model, or an imported file.
3. Give each position a quantity and a unit rate. Pull rates from a cost base with the search panel, or build a rate from an assembly, which is a reusable recipe of labour, material and equipment components.
4. Add the money the measured work does not yet cover: markups for overhead, profit, tax and contingency; allowances for provisional and prime-cost sums; and preliminaries for site establishment and other time-related costs.
5. Watch the live quality score and the cost-per-square-metre benchmark as you work. Fix anything the validation flags, then export the result as Excel, CSV, a PDF report, or GAEB XML for tender exchange.

## How it connects

The BOQ is the crossroads of the platform. Quantities flow into it from [takeoff](./quantity-takeoff.md) and from [BIM](./bim-to-cost-and-carbon.md). Rates flow into it from the [world cost bases](./world-cost-bases.md) and from your own assemblies and catalogs. Once positions are priced, they feed the [4D schedule and 5D cost model](./planning-and-cost-control.md), the [carbon account](./bim-to-cost-and-carbon.md), the [tender packages](./tendering-and-bids.md) and the reports. The [validation pipeline](./validation.md) scores the whole thing and links every finding back to the exact position, and [design options](./design-options.md) let you compare a full priced BOQ across competing variants.

## Supporting capabilities

Around the core editor, several modules deepen the estimate when you need them: assemblies and calculations for reusable rate build-ups, an all-in labour and crew rate build-up, waste factors to move from net to gross quantities, production-norm expansion to derive resource demand from coefficients, a resource summary that turns the estimate into a procurement-ready schedule of labour, materials and plant, and a basis-of-estimate draft that records the inclusions, exclusions and assumptions behind the number.

## Risk contingency in the estimate

The cost-risk panel turns a Monte Carlo run into one contingency line in the bill, only after you confirm the percentile and the amount you saw. The simulation can sample the bill's own line ranges or the project risk register (open risks only; closed, retired and rejected ones are left out, and all priced risks must share the bill's currency). A register run stores the list of risks behind it, so the money traces back to register items, and the line is flagged stale when a risk changes. The amount can be fixed, or a percentage of the direct cost that follows later quantity edits. Exports label the line with its percentile and source, and validation warns when the line holds less than the median estimate or when a manual contingency line sits beside it.
