// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run the contract through the epittetoi fedezetkezelo" (HU).
//
// On the contracts the construction decree covers, the client's money does not
// reach the contractor directly. It sits with a fedezetkezelo and is released
// against a signed teljesitesigazolas once the subcontractors have been
// declared, which is the mechanism Hungary put against chain debt. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-the-contract-through-the-epittetoi-fedezetkezelo",
  order: 1249,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "developer-client", "cost-consultant"],
  roles: ["commercial-manager", "finance-manager", "contract-administrator", "quantity-surveyor"],
  region: "HU",
  icon: "Landmark",
  titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.title",
  titleDefault: "Run the contract through the epittetoi fedezetkezelo",
  descKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.desc",
  descDefault:
    "Settle whether the construction escrow applies before the contract is signed, register the contract and its cover with the fedezetkezelo, claim each period against a signed teljesitesigazolas, declare what your subcontractors are owed before your own money is released, and close the account at the final settlement.",
  longDescKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.longdesc",
  longDescDefault:
    "Chain debt is the Hungarian construction industry's oldest failure: a client pays, a main contractor holds the money, and a subcontractor three tiers down is never paid for work already built in. The construction execution decree answers it structurally rather than by exhortation. On the contracts it covers, the consideration is placed with an escrow manager, the state treasury on a public works contract, and it leaves that account only against a performance certificate and only once the contractor has declared what it owes below. For the commercial team that changes the shape of the month: the invoice is no longer the instrument that gets you paid, the certificate plus the subcontractor declaration is, and one missing declaration holds the whole release rather than one line of it.",
  estMinutes: 15,
  steps: [
    {
      id: "applies",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.in.draft", label: "Draft contract" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.in.value", label: "Contract value and route" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.out.answer", label: "Escrow applies or does not" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.out.manager", label: "Fedezetkezelo identified" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.title",
      titleDefault: "Settle whether the escrow applies before you sign",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.what",
      whatDefault:
        "Test the contract against the decree rather than against what the last job did: whether the work is procured under the public procurement act, what the contract value is, and which of those triggers the escrow. Record who the fedezetkezelo will be, the state treasury on a public works contract or a financial institution otherwise, and write the arrangement into the contract instead of bolting it on afterwards.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.applies.why",
      whyDefault:
        "Both the value that triggers the escrow and the range of contracts it covers have moved over the years, so a rule remembered from a previous job is the wrong instrument to answer this with. Discovering the obligation after signature means renegotiating the payment mechanism with a contractor who has already priced a different one, and the price of that renegotiation is always the client's.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "register",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.in.signed", label: "Signed contract" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.in.cover", label: "Cover to be deposited" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.out.account", label: "Escrow account open" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.out.schedule", label: "Payment schedule registered" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.title",
      titleDefault: "Register the contract and deposit the cover",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.what",
      whatDefault:
        "Register the contract with the fedezetkezelo, open the escrow account and place in it the consideration together with the performance security the contract calls for. Record the payment schedule the same way both parties will claim against it, and link the arrangement to the e-epitesi naplo the work will be recorded in.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.register.why",
      whyDefault:
        "The escrow exists so that the money is demonstrably there before the work starts, which is what a subcontractor is really relying on when it mobilises. A schedule registered differently from the one the site works to produces a claim the escrow manager cannot match to anything, and the release stops while two spreadsheets are reconciled.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "measure",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.in.koltsegvetes", label: "Contract koltsegvetes" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.in.done", label: "Work done in the period" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.out.valuation", label: "Period valuation" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.out.cumulative", label: "Cumulative against the schedule" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.title",
      titleDefault: "Measure the period against the contract koltsegvetes",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.what",
      whatDefault:
        "Value the period tetel by tetel against the koltsegvetes the contract carries, keeping the anyag and the dij apart as the bill keeps them, and set the cumulative figure against the registered payment schedule so the two are read together rather than reconciled later.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.measure.why",
      whyDefault:
        "The escrow releases against a certified amount, and the certificate is only as quick to obtain as the measurement behind it is easy to check. A valuation that departs from the contract's own line structure forces the muszaki ellenor to rebuild it before signing anything, and every day of that is a day the money is not moving.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "claim",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.in.valuation", label: "Period valuation" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.in.certificate", label: "Signed teljesitesigazolas" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.out.claim", label: "Release request lodged" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.out.invoice", label: "Szamla against the certificate" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.title",
      titleDefault: "Claim only against a signed performance certificate",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.what",
      whatDefault:
        "Get the teljesitesigazolas signed for the measured period first, then raise the szamla for exactly that amount and lodge the release request with the fedezetkezelo, quoting the certificate. Where the certificate is refused or left unanswered, record the refusal and its date rather than invoicing anyway.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.claim.why",
      whyDefault:
        "The escrow manager checks the request against the certificate, so an invoice raised without one has nothing to be matched to and is simply held. Recording a refusal with its date is what preserves the route to have the performance certified by an expert body instead of leaving the contractor arguing about an invoice nobody ever accepted.",
      moduleLabel: "Payments",
      moduleLabelKey: "finance.payments",
      to: "/projects/:projectId/finance?tab=payments",
    },
    {
      id: "subs",
      icon: "Users",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.in.subcontracts", label: "Subcontract register" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.in.owed", label: "Amounts owed below" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.out.declaration", label: "Subcontractor declaration" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.out.released", label: "Release cleared" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.title",
      titleDefault: "Declare what the subcontractors are owed before you are paid",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.what",
      whatDefault:
        "Keep the register of subcontractors and their certified amounts current, and file the declaration the fedezetkezelo requires with each release request, showing what each one is owed for the period and what has been settled. Reconcile it against their own certificates rather than against your ledger alone.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.subs.why",
      whyDefault:
        "This declaration is the whole point of the mechanism: the main contractor's money is released on the condition that the chain below it is being paid, so one omitted subcontractor holds the entire release and not just their share. Reconciling to their certificates also catches the case where a subcontractor believes it has been certified for more than you recorded, which is far cheaper to find now than at the final settlement.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "clock",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.in.certificate", label: "Signed teljesitesigazolas" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.in.terms", label: "Payment terms" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.out.due", label: "Payment due date" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.out.interest", label: "Late payment interest" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.title",
      titleDefault: "Let the statutory payment days run from the certificate",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.what",
      whatDefault:
        "Put the contract on the Hungarian payment regime and count from the event the law counts from, the performance being certified, not the day the invoice was posted. Record the shorter run that applies to a public client and the longer one a business client may agree, and let the module compute the due date and the interest that follows it.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.clock.why",
      whyDefault:
        "A term agreed beyond what the law allows is not enforceable simply because both parties signed it, and the interest on late payment runs at a statutory rate rather than a negotiated one. A due date computed from the certificate turns slow payment into a claim with a number, which is the only version of that conversation that ends.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "close",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.in.handover", label: "Handover record" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.in.balance", label: "Balance in the account" },
      ],
      outputs: [
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.out.settlement", label: "Final settlement" },
        { labelKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.out.closed", label: "Escrow account closed" },
      ],
      titleKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.title",
      titleDefault: "Close the account at the final settlement",
      whatKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.what",
      whatDefault:
        "Take the works over with the outstanding items listed, settle the final account against the cumulative certificates, release or convert the performance security according to what the contract says the guarantee period needs, and ask the fedezetkezelo to close the account with a statement of everything paid in and out.",
      whyKey: "cases.run_the_contract_through_the_epittetoi_fedezetkezelo.step.close.why",
      whyDefault:
        "An escrow account left open after handover keeps money immobilised that both sides have use for, and it drifts out of anybody's ownership once the project team disperses. The closing statement is also the single document that proves the chain was paid, which is what answers a subcontractor's claim arriving after everyone involved has moved on.",
      moduleLabel: "Handover & Closeout",
      moduleLabelKey: "closeout.title",
      to: "/closeout",
    },
  ],
};

export default playbook;
