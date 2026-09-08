// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Bid for a government works contract under the Tenders Law" (SA).
//
// A Saudi public works bid is refused for eligibility far more often than it
// is lost on price. The classification certificate has to name the field, the
// activity and the grade the works fall in, the initial guarantee has to be
// lodged in the right form and stay valid past the opening, and the local
// content position has to be evidenced rather than asserted. This case runs
// one bid from the decision to compete through to the award, and ends where
// the guarantees change shape. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "bid-for-a-government-works-contract-under-the-tenders-law",
  order: 1192,
  region: "SA",
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "commercial-manager", "quantity-surveyor"],
  stage: "procure",
  icon: "Landmark",
  titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.title",
  titleDefault: "Bid for a government works contract under the Tenders Law",
  descKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.desc",
  descDefault:
    "Check you are eligible to bid at all, read the tender into a priced bill, build the local content position from your supply chain, lodge the initial guarantee, submit before the envelopes open, and turn the initial guarantee into the final one when the award lands.",
  longDescKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.longdesc",
  longDescDefault:
    "Public procurement in the Kingdom runs on the Government Tenders and Procurement Law and its Implementing Regulations, and it is transacted electronically through the government procurement platform. Two gates stand in front of the price. The first is the Contractor Classification Law: a government entity may not award works subject to classification to a contractor who is not classified in the matching field, activity and grade, so a bid from an unclassified or wrongly classified firm is not a weak bid, it is not a bid. The second is the initial guarantee, whose amount and validity the tender documents set and whose expiry is usually written in Hijri months, which is where a bid extension quietly kills a guarantee. Note also that the Council of Ministers approved a new Government Tenders and Procurement Law in August 2026, so the first thing to record about any live tender is which law and which regulations it is being run under.",
  estMinutes: 20,
  steps: [
    {
      id: "eligible",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.in.notice", label: "Tender notice" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.in.certificates", label: "Company certificates" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.out.decision", label: "Bid or no bid decision" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.out.gaps", label: "Eligibility gaps listed" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.title",
      titleDefault: "Establish that you may bid before you price anything",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.what",
      whatDefault:
        "Open the bid record and check the gates in order: the contractor classification certificate covers this field and activity at a grade that carries this contract value, the commercial registration and the chamber membership are current, the Saudization band is not one that suspends government services, and the zakat, tax and social insurance certificates are in date. Where one is missing, that is the work, not the estimate.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.eligible.why",
      whyDefault:
        "Under the Contractor Classification Law the classification is not a credential that helps, it is a condition of award. Grades run from one to five and each carries a ceiling on the value of works it may take, so a firm classified in the right field at too low a grade is refused on a contract it can build. Two weeks of estimating spent before anybody looked at the certificate is the most common way a Saudi contractor loses money on a tender he never entered.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "read",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.in.documents", label: "Tender documents" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.in.addenda", label: "Addenda issued" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.out.structure", label: "Bill structure loaded" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.out.questions", label: "Clarifications raised" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.title",
      titleDefault: "Read the tender into a structure you can price",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.what",
      whatDefault:
        "Bring the schedule of quantities in as it was issued, keeping the authority's item numbering, and record every addendum against the version it changed. Raise clarifications inside the window the tender gives, because a question asked after it closes is a question you will answer yourself in the price.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.read.why",
      whyDefault:
        "Government bids are compared item by item against the authority's own numbering, so a bid that renumbers or merges items is hard to evaluate and easy to set aside. Keeping the issued structure intact also means an addendum landing three days before the deadline changes two lines rather than forcing a re-read of the whole bill.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.in.structure", label: "Bill structure loaded" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.in.rates", label: "Rates and resource costs" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.out.priced", label: "Priced bill" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.out.basis", label: "Basis of the price recorded" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.title",
      titleDefault: "Price it against real rates, with the basis written down",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.what",
      whatDefault:
        "Build each rate from labour, plant, material and subcontract rather than from last year's bid, and record what the rate assumed: the productivity, the working week of Sunday to Thursday, the reduced hours the Labour Law imposes during Ramadan, and the site conditions in the region the works are in.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.price.why",
      whyDefault:
        "A government contract is fixed price against measured quantities, so the rate is the only place a wrong assumption can be recovered from, and it cannot. Writing the assumption next to the rate is also what makes a later claim about changed conditions arguable, because you can show what was priced rather than assert what was meant.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "content",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.in.suppliers", label: "Supplier and subcontract list" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.in.requirement", label: "Local content requirement" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.out.position", label: "Local content position" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.out.evidence", label: "Certificates collected" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.title",
      titleDefault: "Build the local content position out of the supply chain",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.what",
      whatDefault:
        "Split the planned spend into what stays in the Kingdom and what leaves it, package by package, and collect the evidence behind each line: your own local content certificate, the certificates of the subcontractors and suppliers you are relying on, and the products that sit on the mandatory list of national products.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.content.why",
      whyDefault:
        "Local content in government procurement is administered by the Local Content and Government Procurement Authority, which sets the measurement methodology and issues the certificates, and it is scored rather than admired. A percentage asserted in a covering letter is worth nothing at evaluation. A percentage built from named suppliers with certificates behind them survives the check and is also the thing you will have to deliver against afterwards.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "guarantee",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.in.priced", label: "Bid total" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.in.terms", label: "Guarantee terms in the tender" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.out.bond", label: "Initial guarantee issued" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.out.validity", label: "Validity recorded" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.title",
      titleDefault: "Lodge the initial guarantee and record what it says",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.what",
      whatDefault:
        "Instruct the bank for the initial guarantee at the percentage of the bid the tender documents state, which the Tenders Law will not let fall below one percent, and record three things about it: the amount, the beneficiary exactly as the tender names it, and the expiry date with the calendar it is written in. Guarantee validity in the Kingdom is commonly expressed in Hijri months.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.guarantee.why",
      whyDefault:
        "The initial guarantee is what makes the bid real, and it is refused for form as readily as for amount, a beneficiary named loosely being the usual cause. The expiry is the quiet one. Where the authority extends the bid validity and the guarantee was written for a fixed number of Hijri months, the extension outlives the guarantee, and a bid with a lapsed guarantee is excluded without anybody having criticised the price.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "submit",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.in.bid", label: "Complete bid pack" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.in.deadline", label: "Submission deadline" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.out.submitted", label: "Bid submitted" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.out.receipt", label: "Proof of what was sent" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.title",
      titleDefault: "Submit it, and keep proof of what you submitted",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.what",
      whatDefault:
        "Sign and lodge the bid through the government procurement platform before the deadline, and keep the signed set exactly as it went: the priced bill, the technical proposal, the guarantee, the certificates and the addenda you confirmed receipt of.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.submit.why",
      whyDefault:
        "Bids are opened at a fixed time and a late submission is not considered, whatever the reason. The archived set matters afterwards rather than before: when the authority asks a month later whether you priced against addendum three, the answer should be a document with a signature on it, not a recollection.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "award",
      icon: "Trophy",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.in.letter", label: "Award notification" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.in.bond", label: "Initial guarantee" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.out.final", label: "Final guarantee lodged" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.out.contract", label: "Contract on record" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.title",
      titleDefault: "Turn the initial guarantee into the final one",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.what",
      whatDefault:
        "On the award notification, instruct the final guarantee at five percent of the contract value in favour of the government entity and lodge it inside the period the award letter allows, then register the contract with its payment regime, its guarantees and the advance payment arrangement, where the contract carries one, secured by a bank guarantee for the whole of the advance.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.award.why",
      whyDefault:
        "The final guarantee is a condition of signing rather than an administrative follow up, and the period to produce it is short. A contractor who treats the award as the finish line loses days at the bank and can forfeit the initial guarantee for failing to complete. The advance payment guarantee belongs on the same record because the advance is recovered through the interim certificates and the guarantee is reduced as it is recovered, and the two figures only agree if somebody is reading them together.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "clocks",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.in.guarantees", label: "Guarantees and their expiries" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.in.certificates", label: "Company certificates" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.out.register", label: "Expiry register" },
        { labelKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.out.owners", label: "An owner on each date" },
      ],
      titleKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.title",
      titleDefault: "Put every date that can lapse on one register",
      whatKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.what",
      whatDefault:
        "Register the dates that carry a consequence with the person who owns each one: the guarantee expiries in the calendar they were written in, the classification certificate renewal, the zakat and tax certificates, and the bid validity where an award has not yet landed.",
      whyKey: "cases.bid_for_a_government_works_contract_under_the_tenders_law.step.clocks.why",
      whyDefault:
        "Every item on that list expires quietly and none of them announce it. A classification certificate that lapses mid tender disqualifies a bid that was winning, and a guarantee written in Hijri months runs out about eleven days earlier each year than a reader working in Gregorian months expects. One register with owners is the difference between a renewal and an incident.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
