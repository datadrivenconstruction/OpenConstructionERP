// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Bid a state contract under 44-FZ" (RU).
//
// Establish which of the two public procurement laws governs the purchase,
// rebuild the starting maximum price from the customer's own smeta, price your
// own risk into the offer, submit the application with its security and take the
// contract onto the payment clock the statute sets. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "bid-a-state-contract-under-44-fz",
  order: 1304,
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["procurement-buyer", "estimator", "commercial-manager", "contract-administrator"],
  region: "RU",
  icon: "Gavel",
  titleKey: "cases.bid_a_state_contract_under_44_fz.title",
  titleDefault: "Bid a state contract under 44-FZ",
  descKey: "cases.bid_a_state_contract_under_44_fz.desc",
  descDefault:
    "Read the notice to settle whether 44-FZ or 223-FZ governs, rebuild the NMCK from the customer's smeta, price your own risk into the offer, submit the zayavka with its security and take the contract onto the payment clock the law sets.",
  longDescKey: "cases.bid_a_state_contract_under_44_fz.longdesc",
  longDescDefault:
    "Two laws govern public buying in Russia and they are not variations of one another. 44-FZ binds state and municipal customers spending budget money, and it fixes the procedures, the documents and the deadlines itself, leaving the customer almost no discretion. 223-FZ binds state-owned companies and their subsidiaries, which buy under their own published procurement regulation, so the rules change from customer to customer and the first thing to read is that regulation rather than the statute. Bidding one as though it were the other is how a technically strong contractor is rejected on formal grounds before the price envelope is ever opened.",
  estMinutes: 15,
  steps: [
    {
      id: "regime",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.regime.in.notice", label: "Published notice" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.regime.in.regulation", label: "Customer's procurement regulation" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.regime.out.law", label: "Governing law identified" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.regime.out.rules", label: "Rulebook that applies" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.regime.title",
      titleDefault: "Establish which law the purchase runs under",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.regime.what",
      whatDefault:
        "Read the notice in the unified information system and settle three things before touching the price: which law it names, 44-FZ or 223-FZ, which procedure is being run, and for a 223-FZ purchase which version of the customer's own procurement regulation applies. Note as well whether the purchase is reserved for small business.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.regime.why",
      whyDefault:
        "Under 44-FZ the procedure, the forms and the grounds for rejecting an application come from the statute and are identical for every customer in the country. Under 223-FZ they come from a regulation the customer writes itself, so two purchases run by two state companies can demand entirely different documents. Reading the wrong rulebook ends in rejection on formal grounds with your price never opened.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "nmck",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.in.smeta", label: "Customer's smeta" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.in.own", label: "Your own rates and norms" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.out.rebuilt", label: "Rebuilt price" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.out.gaps", label: "Positions that do not hold" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.title",
      titleDefault: "Rebuild the NMCK from the customer's smeta",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.what",
      whatDefault:
        "Load the smeta published with the notice position by position and price it against your own rates and your own norms. Mark every position where the quantity, the norm or the price does not survive contact with how the work is actually done, and total what the difference is worth.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.nmck.why",
      whyDefault:
        "The NMCK is both a ceiling and a claim about what the work costs. If it was built on a stale index or on a norm that does not fit the method the site will use, you learn it either now, while you can still decide not to bid, or eleven months in while carrying the difference yourself. Under 44-FZ the contract price is fixed on signature, so there is no later.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "risk",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.risk.in.rebuilt", label: "Rebuilt price" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.risk.in.terms", label: "Security and payment terms" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.risk.out.offer", label: "Offer price" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.risk.out.floor", label: "Discount you can carry" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.risk.title",
      titleDefault: "Price your own overhead, profit and risk into the offer",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.risk.what",
      whatDefault:
        "In the bill's Markups & Overheads panel, set the overhead and profit this company actually needs rather than the normed percentages the NMCK was built with, add what the bid security, the performance security and the payment terms cost you in working capital, and work out the largest discount you could still carry at the end of the job.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.risk.why",
      whyDefault:
        "Normed NR and SP describe an average contractor on an average job, which is not this one. The discount settled here governs the whole contract, because a state contract is not renegotiated, and a bidder who goes a quarter or more below the NMCK triggers the anti-dumping measures in article 37 of 44-FZ and must post increased security or prove good faith before the contract can be signed.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "bid",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.bid.in.offer", label: "Offer price" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.bid.in.checklist", label: "Documents the notice lists" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.bid.out.zayavka", label: "Submitted zayavka" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.bid.out.security", label: "Bid security posted" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.bid.title",
      titleDefault: "Assemble the zayavka and post its security",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.bid.what",
      whatDefault:
        "Build the application the notice actually asks for: the price, the consent to the customer's terms, the declarations about the bidder, the evidence of comparable experience where the purchase demands it, and the bid security in one of the forms the notice allows. Check every deadline against the notice rather than against what the last purchase did.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.bid.why",
      whyDefault:
        "Most public work is lost on a missing declaration or on security posted in a form the notice did not accept, not on price. The commission checks the application against the notice mechanically, and once the deadline passes there is no route to add what was left out.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "contract",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.contract.in.award", label: "Award decision" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.contract.in.performance", label: "Performance security" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.contract.out.signed", label: "Signed contract on record" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.contract.out.terms", label: "Terms everyone works from" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.contract.title",
      titleDefault: "Take the contract at the price you offered",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.contract.what",
      whatDefault:
        "Sign at your offered price with the performance security in place, and record the terms that will govern the whole job in one place: the intermediate and final deadlines, the penalty regime, the advance if there is one, the retention, and the narrow grounds on which the price or the scope may change.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.contract.why",
      whyDefault:
        "A contract under 44-FZ is signed on the customer's terms and its price is fixed by the law, with only the grounds the statute names for changing it afterwards. Whatever was not priced into the bid is yours to carry, so the contract record has to be the version the site, the estimator and the accounts all read, not a copy in one person's mailbox.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "clock",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.clock.in.contract", label: "Signed contract" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.clock.in.acceptance", label: "Acceptance document" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.clock.out.due", label: "Payment due date" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.clock.out.interest", label: "Statutory delay interest" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.clock.title",
      titleDefault: "Put the payment term on the clock the law sets",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.clock.what",
      whatDefault:
        "Put the contract on the 44-FZ public regime and let it count from the right event, the customer's signature on the acceptance document rather than the day you sent it. That gives seven working days to payment, ten where settlements run under treasury support or the acceptance was signed outside the unified system, which the regime does not compute for you, and the interest on delay is a statutory rate rather than a negotiated one.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.clock.why",
      whyDefault:
        "The term comes from article 34 of 44-FZ and is not a matter of local custom, so a customer paying late is in default from a date that can be named to the day. A clock started on the right event is what turns a conversation about slow payment into a claim with a figure attached.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "deadlines",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.in.milestones", label: "Contract deadlines" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.in.notices", label: "Notices you owe" },
      ],
      outputs: [
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.out.calendar", label: "Deadlines under watch" },
        { labelKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.out.warning", label: "Warning before each date" },
      ],
      titleKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.title",
      titleDefault: "Watch the deadlines the penalty regime hangs on",
      whatKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.what",
      whatDefault:
        "Load the intermediate and final deadlines the contract sets together with the notices you owe the customer, and let each one warn you before it lands instead of appearing in a letter afterwards.",
      whyKey: "cases.bid_a_state_contract_under_44_fz.step.deadlines.why",
      whyDefault:
        "On a state contract a missed deadline produces a penalty calculated by formula, and a termination for your default puts the company into the register of unscrupulous suppliers, which closes public work to it for two years. The penalty is arithmetic and survivable, the register is not, and both start from a date nobody was watching.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
