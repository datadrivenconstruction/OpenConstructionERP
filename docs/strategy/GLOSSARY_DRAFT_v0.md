# Glossary - canonical English draft (for founder sign-off)

Clarity plan Q1. This is the one hard blocker for the platform-wide glossary:
the canonical English wording has to be signed off BEFORE it is translated into
26 locales, because re-wording after the x27 translation is expensive.

How to use this file: read each definition, edit anything that is off, then tell
me "glossary signed" (or hand back edits). On sign-off I add every `glossary.<term>`
(and `glossary.<term>_example`) to `en.ts` and run one i18n sweep so all 26 locales
get them. The shared `<GlossaryTerm>` and `<GridHeaderHelp>` components already read
these keys, so the definitions light up the moment they land - no code changes.

Style rules used below:
- Plain language first, the jargon term in parentheses after.
- About 20 words max per definition.
- Finance and measurement terms carry a one-line worked example.
- No competitor or vendor names anywhere.

## Finance and cost control

- **retention** - Money the client holds back from each payment until the work is
  finished and accepted, as security.
  - example: On a 100,000 invoice with 5% retention, 5,000 is withheld and released at handover.

- **variance** - The gap between what you planned to spend or earn and what actually
  happened. Positive or negative.
  - example: Budget 80,000, actual 86,000, variance is -6,000 (over budget).

- **committed** - Cost you have already promised through a signed order or contract,
  even if no invoice has arrived yet.
  - example: A subcontract is signed for 40,000, so 40,000 is committed before any invoice.

- **forecast** - Your best current estimate of the final cost, based on what is spent,
  committed, and still to come (forecast final cost / EAC).
  - example: Spent 30,000 + remaining estimate 50,000 gives a forecast of 80,000.

- **payable** - Money you owe to suppliers and subcontractors for work or goods already
  received (accounts payable).
  - example: A delivered material invoice for 12,000 not yet paid sits in payables.

- **receivable** - Money owed to you by the client for work you have invoiced but not yet
  been paid for (accounts receivable).
  - example: A submitted application for 60,000 awaiting payment is a receivable.

- **CPI** - Cost efficiency: value of work done divided by what it cost. Above 1 is under
  budget, below 1 is over (cost performance index).
  - example: 90,000 of work done for 100,000 spent gives a CPI of 0.90 (over budget).

- **SPI** - Schedule efficiency: value of work done divided by the value you planned to have
  done by now. Above 1 is ahead (schedule performance index).
  - example: Done 90,000 against a planned 100,000 gives an SPI of 0.90 (behind plan).

- **EVM** - A method that compares planned value, actual cost, and the value of work really
  completed to show cost and schedule health (earned value management).
  - example: Planned 100k, spent 110k, earned 95k means you are over cost and behind schedule.

- **escrow** - Funds held by a neutral third party and released only when agreed conditions
  are met.
  - example: A deposit is held in escrow until both sides sign the handover certificate.

- **unit_rate** - The price for one unit of a work item, before multiplying by quantity
  (unit price).
  - example: 45 per m2 of plaster x 200 m2 gives a line total of 9,000.

- **price_matrix** - A table of rates that vary by attributes such as region, supplier, or
  tier, used to pick the right price automatically.
  - example: The same item costs 45 in one region and 52 in another via the price matrix.

## Estimating and measurement

- **takeoff** - Measuring quantities (lengths, areas, counts) from drawings or models to feed
  the estimate (quantity takeoff).
  - example: Counting 24 doors on a floor plan is a takeoff of 24 units.

- **assembly** - A reusable recipe that bundles several cost items into one priced unit, like
  a wall build-up.
  - example: A concrete wall assembly bundles concrete, formwork, and rebar into one m2 rate.

- **din276** - The German cost-classification standard that groups building costs into cost
  groups (Kostengruppen).

- **nrm** - The UK measurement and cost-classification rules for estimates and bills of
  quantities (New Rules of Measurement).

- **gaeb** - The German electronic exchange format for tenders and bills of quantities, used
  to send and receive priced work items.

- **masterformat** - The North American standard that organises construction work into numbered
  divisions and sections.

## Schedule

- **float** - How long an activity can slip without delaying the project finish (slack).
  - example: An activity with 5 days of float can start up to 5 days late with no overall delay.

- **makespan** - The total time from the first activity start to the last activity finish across
  the whole plan.
  - example: Start on day 0, last finish on day 120, makespan is 120 days.

- **crew_flow** - Keeping a crew moving steadily from one location to the next without gaps or
  clashes (work continuity).
  - example: The tiling crew flows floor by floor with no idle days between them.

## BIM and coordination

- **LOD** - How detailed and reliable a model element is, from rough placeholder to
  construction-ready (level of development).

- **IDS** - A machine-readable rulebook that states exactly which properties a model must
  carry to be accepted (information delivery specification).

- **COBie** - A structured handover spreadsheet of asset data (spaces, equipment, warranties)
  for the building operator.

- **clearance** - The required free gap between elements or around equipment for access, safety,
  or install.
  - example: A valve needs 600 mm clearance for maintenance access.

- **penetration** - A hole or sleeve through a wall, floor, or beam for a pipe, duct, or cable.
  - example: A duct passing through a fire wall is a penetration that must be fire-stopped.

- **set_a_b** - The two element groups compared against each other in a clash test (clash set A
  vs set B).
  - example: Set A is the ductwork, set B is the structure; the test finds where they collide.

- **datum** - A fixed reference point or level that all measurements are taken from.
  - example: Finished floor level is the datum that heights on the drawing are measured from.

- **coordinate_system** - The shared origin and axes that place every model in the same real-world
  position.
  - example: Two models align only when they use the same coordinate system and origin.

- **anchor_drift** - When models slowly fall out of alignment because their shared reference point
  has moved or been reset.
  - example: A re-exported model lands 2 m off because of anchor drift in its origin.

## Documents and CDE (ISO 19650)

- **suitability_code** - A short status code on a document showing how far it can be trusted and
  what it may be used for.
  - example: Code S2 means "for information", not yet approved to build from.

- **wip_shared_published** - The three states a document moves through: private work in progress,
  shared with the team, then published as approved.
  - example: A drawing goes from WIP to Shared for review, then Published for construction.

- **noc** - A formal letter confirming an authority or party has no objection to the work
  proceeding (no objection certificate).

## Quality and safety

- **capa** - The actions taken to fix a problem and stop it happening again (corrective and
  preventive action).
  - example: After a recurring defect, the CAPA is a process change plus a check step.

- **jsa** - A task-by-task breakdown that identifies hazards and controls before work starts
  (job safety analysis).

- **ppe** - The protective gear a worker must wear for a task, such as a helmet, gloves, or
  harness (personal protective equipment).

- **ncr** - A formal record that something does not meet the specification and must be resolved
  (non-conformance report).

- **snag** - A small defect found during inspection that needs fixing before handover (punch-list
  item).
  - example: A scratched door noted at inspection is a snag to fix before sign-off.

## Real estate

- **spa** - The binding contract that sets the price and terms for buying or selling a property
  or asset (sale and purchase agreement).

## Notes for the founder
- The seed set is ~39 terms (clarity plan P0). If any term here is one your users never see,
  say so and I will drop it. If a key term is missing, add it.
- Worked examples are deliberately only on the finance and measurement terms where a number
  makes the meaning click. I can add or remove examples per your call.
- Definitions avoid naming any standard's owner or any product; only the standard's own name
  is used (DIN 276, NRM, GAEB, MasterFormat, COBie, ISO 19650), which are open standards, not
  vendor brands.
