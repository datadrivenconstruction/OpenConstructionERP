// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a compensation event and a JBCC contract instruction" (ZA).
//
// Large South African public clients tend to contract on NEC, and building
// work tends to run on the JBCC principal building agreement. The same event
// on site is handled in two quite different shapes: NEC assesses time and
// money together in one quotation, while the JBCC agreement splits them into a
// valuation under clause 26.0 and a revision of the date for practical
// completion under clause 23.0, each with its own notice and its own
// forfeiture. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-compensation-event-and-a-jbcc-contract-instruction",
  order: 1344,
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  roles: ["commercial-manager", "quantity-surveyor", "contract-administrator"],
  region: "ZA",
  stage: "build",
  icon: "GitCompare",
  titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.title",
  titleDefault: "Price a compensation event and a JBCC contract instruction",
  descKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.desc",
  descDefault:
    "Work out which contract you are on, give the notice that contract wants inside the days it gives you, price the change on the rules that contract uses, and get the time and the money settled instead of carried to the final account.",
  longDescKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.longdesc",
  longDescDefault:
    "A change on site is one event and two entirely different pieces of paperwork depending on the contract. On NEC a compensation event under clause 60.1 is notified, quoted and assessed once, and the quotation carries the effect on the Prices and on the Completion Date together. Under the JBCC principal building agreement a contract instruction under clause 17.0 is valued under clause 26.0 while the time it costs you is a separate claim under clause 23.0, with a separate notice and a separate deadline, and missing that deadline forfeits the claim outright rather than weakening it. Contractors who run both kinds of contract in the same office lose money by using one habit on the other.",
  estMinutes: 13,
  steps: [
    {
      id: "regime",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.in.contract", label: "Signed contract" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.in.data", label: "Contract data" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.out.regime", label: "Contract regime" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.out.clocks", label: "Notice periods" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.title",
      titleDefault: "Read the change machinery off the contract",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.what",
      whatDefault:
        "Establish which form the job runs on and write down the periods that go with it. On NEC that is eight weeks to notify a compensation event under clause 61.3 and three weeks to submit a quotation under clause 62.3. Under the JBCC principal building agreement it is twenty working days to give notice of a claim for revision of the date for practical completion under clause 23.4.2, twenty working days to give notice of expense and loss under clause 26.5, and forty working days to submit the substantiated claim in either case.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.regime.why",
      whyDefault:
        "Both forms make a late notice fatal rather than untidy. NEC clause 61.3 removes the entitlement to a change in the Prices and the Completion Date where the Contractor did not notify in time, and clause 23.4.2 of the JBCC agreement forfeits the claim. The periods are the first thing to know on a job and the last thing anyone looks up once the argument has started.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "warn",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.in.event", label: "Site event" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.in.programme", label: "Current programme" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.out.entry", label: "Early warning entry" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.out.meeting", label: "Meeting actions" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.title",
      titleDefault: "Put the event on the early warning register",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.what",
      whatDefault:
        "Log the matter the moment somebody sees it coming: what it is, what it could cost in money and in time, and who has to do something about it. On NEC this is the early warning register and it feeds the early warning meeting, where both sides look for ways to avoid or reduce the effect before anyone prices anything.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.warn.why",
      whyDefault:
        "The early warning register is the one part of NEC that is cheaper for both parties than the alternative, because the assessment of a compensation event can take into account what would have happened had the warning been given. There is no equivalent clause in the JBCC agreement, but there is no reason to run a JBCC job without the register either: a change seen four weeks out is a change somebody can still design around.",
      moduleLabel: "Risk Register",
      moduleLabelKey: "nav.risk_register",
      to: "/risks",
    },
    {
      id: "notify",
      icon: "Send",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.in.instruction", label: "Instruction or event" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.in.dates", label: "Date of awareness" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.out.notice", label: "Notice issued" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.out.deadline", label: "Substantiation deadline" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.title",
      titleDefault: "Give the notice, and give it in writing",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.what",
      whatDefault:
        "Issue the notice the contract asks for, naming the clause relied on, the cause, and the date you became aware. Under the JBCC agreement a claim for revision of the date for practical completion must go on to state the effect on the critical path and the extension asked for in working days, per clause 23.6, and that comes with the substantiated claim inside forty working days.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.notify.why",
      whyDefault:
        "Clause 17.5 of the JBCC principal building agreement gives an oral contract instruction no force or effect, so a change agreed on site and never written down is a change you did for free. The notice is also the only thing that stops the clock, and on both forms a notice that names no clause and no date is treated as correspondence rather than as a notice.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "record",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.in.notice", label: "Issued notice" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.in.scope", label: "Changed scope" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.out.entry", label: "Change register entry" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.out.status", label: "Status and owner" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.title",
      titleDefault: "Open a change with a number and an owner",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.what",
      whatDefault:
        "Open a numbered change carrying the instruction or the event, its clause, the notice date, the quotation or claim due date, and the person who owes the next move. Keep it open until both the money and the time have been settled, not until one of them has.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.record.why",
      whyDefault:
        "Clause 23.8 of the JBCC agreement deems the principal agent's failure to act within twenty working days a refusal, which starts a dispute clock the contractor has to notice for itself. On NEC clause 64 lets the Project Manager assess the event where the quotation is not submitted or not accepted. Both are silences that cost the party that was not watching, and a register with an owner and a due date is what makes silence visible.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.in.rates", label: "Priced document rates" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.in.actuals", label: "Labour, plant and materials" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.out.valuation", label: "Valuation" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.out.basis", label: "Stated basis" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.title",
      titleDefault: "Value the change on the rules the contract gives",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.what",
      whatDefault:
        "Under the JBCC principal building agreement work through clause 26.2 in order: work of a similar character at the rates in the priced document, work that is not of a similar character at rates based on those rates, and only where neither applies the actual cost of labour, plant and materials plus a ten per cent mark-up, with omissions taken out at priced document rates. On NEC the change to the Prices is assessed on the effect on Defined Cost plus the Fee, forecast forward rather than measured back.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.price.why",
      whyDefault:
        "These are two genuinely different theories of value and using the wrong one loses real money in a predictable direction. A JBCC valuation reaches cost plus ten per cent only after the bill rates have been ruled out, so a contractor who starts at cost concedes the argument. An NEC assessment is a forecast, so a contractor who waits to measure the actual cost has valued it on the wrong basis and usually late.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "time",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.in.baseline", label: "Accepted programme" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.in.impact", label: "Delay evidence" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.out.extension", label: "Extension claimed" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.out.revised", label: "Revised completion date" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.title",
      titleDefault: "Show the delay on the programme, not in a letter",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.what",
      whatDefault:
        "Take the accepted programme, put the event into it and show what moves on the critical path and by how much. On NEC the effect on the Completion Date belongs in the same quotation as the money. Under the JBCC agreement it is a separate claim, and clause 23.1 lists the grounds that revise the date without adjusting the contract value while clause 23.2 lists those that revise it with an adjustment.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.time.why",
      whyDefault:
        "The penalty for late completion under clause 24.0 of the JBCC agreement runs from the revised date for practical completion, and it is deducted through the payment certificates. An extension of time that was never granted because nobody demonstrated the critical path is a penalty paid every week until the job ends, and the difference between the clause 23.1 and clause 23.2 grounds is whether you also get paid for the time.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "certify",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.in.agreed", label: "Agreed valuation" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.in.period", label: "Certificate period" },
      ],
      outputs: [
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.out.certified", label: "Amount certified" },
        { labelKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.out.account", label: "Final account line" },
      ],
      titleKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.title",
      titleDefault: "Get the settled amount into the next certificate",
      whatKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.what",
      whatDefault:
        "Carry the agreed valuation into the next payment certificate rather than holding it for the final account, and close the change with the amount and the time both recorded against it.",
      whyKey: "cases.price_a_compensation_event_and_a_jbcc_contract_instruction.step.certify.why",
      whyDefault:
        "Clause 26.10 of the JBCC principal building agreement requires the final account within sixty working days of practical completion, and clause 26.11 deems it accepted if the contractor does not respond within thirty working days. A change settled month by month arrives at that deadline as arithmetic. A folder of unsettled changes arrives as a negotiation with a deadline attached to it.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
