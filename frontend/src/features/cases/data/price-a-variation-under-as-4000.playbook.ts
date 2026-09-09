// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a variation under AS 4000" (AU).
//
// One change from the direction that authorises it to the adjusted contract
// sum. Clause 36 of AS 4000-1997 is the variation machinery: only the
// Superintendent may direct a variation, the work has to be of a character and
// extent the contract contemplates, and the valuation follows an order that
// starts with prices already agreed and ends with reasonable rates. Clause 41
// puts a time bar around the claim. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-variation-under-as-4000",
  order: 1632,
  region: "AU",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "project-manager"],
  roles: ["quantity-surveyor", "contract-administrator", "commercial-manager", "estimator"],
  stage: "build",
  icon: "GitCompare",
  titleKey: "cases.price_a_variation_under_as_4000.title",
  titleDefault: "Price a variation under AS 4000",
  descKey: "cases.price_a_variation_under_as_4000.desc",
  descDefault:
    "Establish that there is a direction before anyone builds it, keep the cost record while the work is happening, value it in the order clause 36 sets, lodge the claim inside the time the contract allows, carry it into the next progress claim whether or not it is agreed, and adjust the contract sum.",
  longDescKey: "cases.price_a_variation_under_as_4000.longdesc",
  longDescDefault:
    "Under AS 4000 a variation is not whatever the parties later agree was extra. It is work the Superintendent directed, in writing, that is of a character and extent the contract contemplated, and it is valued the way clause 36 says to value it rather than at whatever the market would charge. Two habits decide whether a contractor is paid for it. The first is refusing to treat a conversation on site as a direction, because verbal instructions are the single largest category of unpaid work in Australian construction. The second is keeping the cost record while the work is in front of you, since a valuation argued from a reconstructed timesheet six months later looks exactly like a valuation invented six months later.",
  estMinutes: 16,
  steps: [
    {
      id: "direction",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.direction.in.instruction", label: "Instruction or site request" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.direction.in.contract", label: "Contract scope" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.direction.out.raised", label: "Variation raised and dated" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.direction.out.status", label: "Directed or awaiting a direction" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.direction.title",
      titleDefault: "Establish there is a direction before it is built",
      whatKey: "cases.price_a_variation_under_as_4000.step.direction.what",
      whatDefault:
        "Raise the variation the day the change appears, with the date, who asked, what changed and whether a written direction from the Superintendent exists yet. Where it does not, ask for one and record that you asked, in writing, before the work starts.",
      whyKey: "cases.price_a_variation_under_as_4000.step.direction.why",
      whyDefault:
        "Clause 36 makes the Superintendent's direction the thing that turns extra work into a variation, and an architect or a client representative walking the site is usually neither the Superintendent nor authorised to direct one. Work built on a conversation is work you are asking to be paid for as a favour, and the answer arrives after it is already in the building.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "records",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.records.in.work", label: "Work as it is carried out" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.records.in.resources", label: "Labour, plant and materials used" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.records.out.daywork", label: "Daywork records signed" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.records.out.evidence", label: "Evidence pack for the valuation" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.records.title",
      titleDefault: "Keep the record while the work is in front of you",
      whatKey: "cases.price_a_variation_under_as_4000.step.records.what",
      whatDefault:
        "Collect the daily labour, plant and material records for the varied work as it happens, have them signed on site by the Superintendent's representative where the contract asks for that, and attach the photographs and the delivery dockets to the same entry.",
      whyKey: "cases.price_a_variation_under_as_4000.step.records.why",
      whyDefault:
        "Every valuation route in clause 36 except an agreed price ends up resting on what the work actually took. Records signed at the time settle that in a sentence; records assembled afterwards start a second argument about whether the record is true, and that one is lost even when the claim is good.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "value",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.value.in.raised", label: "Variation raised and dated" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.value.in.rates", label: "Contract rates and prices" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.value.out.valued", label: "Variation valued" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.value.out.route", label: "Which valuation route was used" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.value.title",
      titleDefault: "Value it in the order the clause sets",
      whatKey: "cases.price_a_variation_under_as_4000.step.value.what",
      whatDefault:
        "Work down clause 36 in order rather than jumping to the answer you want. A price the parties have already agreed governs; failing that, the rates and prices in the contract, applied to the varied quantity; failing that, rates in the contract used as a basis where the work is comparable; and only where none of those reach it, reasonable rates and prices. Record which route the valuation used and why the ones above it did not apply.",
      whyKey: "cases.price_a_variation_under_as_4000.step.value.why",
      whyDefault:
        "Naming the route is what makes the number reviewable. A valuation that simply arrives at a figure invites the Superintendent to arrive at a different one, and there is then nothing in dispute except two opinions. A valuation that says which limb of the clause it used and why the earlier limbs did not fit can be disagreed with on a point, and points get resolved.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "claim",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.claim.in.valued", label: "Variation valued" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.claim.in.window", label: "Time the contract allows" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.claim.out.lodged", label: "Claim lodged in time" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.claim.out.dated", label: "Date of lodgement on record" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.claim.title",
      titleDefault: "Lodge the claim inside the time bar",
      whatKey: "cases.price_a_variation_under_as_4000.step.claim.what",
      whatDefault:
        "Serve the claim in the form and inside the period the contract requires, and record the date it went. AS 4000 puts a notification requirement around claims other than progress claims in clause 41, and the Annexure may shorten the period further, so read the Annexure rather than assuming the printed default.",
      whyKey: "cases.price_a_variation_under_as_4000.step.claim.why",
      whyDefault:
        "A time bar does not care whether the claim was good. It is the one defence a principal can run without engaging with the merits at all, and it succeeds on a date rather than on an argument. The claim that is worth the most is usually the one that took the longest to price, which is exactly the one that misses the window.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "progress",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.progress.in.lodged", label: "Claim lodged in time" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.progress.in.period", label: "Current claim period" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.progress.out.included", label: "Variation in the progress claim" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.progress.out.disputed", label: "Disputed amount visible" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.progress.title",
      titleDefault: "Carry it into the progress claim, agreed or not",
      whatKey: "cases.price_a_variation_under_as_4000.step.progress.what",
      whatDefault:
        "Include the valued variation in the next progress claim as its own line, showing what you claim and what has been certified, so an amount in dispute is a visible difference on one line rather than a shortfall on the total.",
      whyKey: "cases.price_a_variation_under_as_4000.step.progress.why",
      whyDefault:
        "A variation held back until it is agreed is a variation that is never claimed and never certified, and the money sits with the contractor for the length of the job. Claiming it keeps it on the record, keeps it inside the payment machinery the contract and the state statute provide, and makes the disagreement about one line instead of the month.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "sum",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.sum.in.agreed", label: "Agreed or determined amount" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.sum.in.contract", label: "Contract sum before" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_under_as_4000.step.sum.out.adjusted", label: "Contract sum adjusted" },
        { labelKey: "cases.price_a_variation_under_as_4000.step.sum.out.running", label: "Running final account" },
      ],
      titleKey: "cases.price_a_variation_under_as_4000.step.sum.title",
      titleDefault: "Adjust the contract sum and keep it running",
      whatKey: "cases.price_a_variation_under_as_4000.step.sum.what",
      whatDefault:
        "Post the agreed or determined amount against the contract so the contract sum moves as each variation closes, and keep the list of open variations with what each one is claimed at beside it.",
      whyKey: "cases.price_a_variation_under_as_4000.step.sum.why",
      whyDefault:
        "A final account is either a running total that both parties have been reading all along or an event, and the event version takes months. Every variation closed as it happened is one fewer item in a negotiation held at the point where the contractor most needs the money and has the least leverage.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
