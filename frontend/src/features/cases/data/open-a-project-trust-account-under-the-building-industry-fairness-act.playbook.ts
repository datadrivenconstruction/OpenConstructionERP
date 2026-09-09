// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Open a project trust account under the Building Industry Fairness
// Act" (AU, Queensland).
//
// The statutory trust framework in chapter 2 of the Building Industry Fairness
// (Security of Payment) Act 2017 (Qld). It is deliberately kept off the payment
// claim clock, which the progress claim case already runs: this one is about
// being a trustee. The head contractor holds the project money and the cash
// retention on trust for its subcontractors, gives the notices the Act
// requires, keeps trust records and submits to account review by the Queensland
// Building and Construction Commission. Security of payment is state law in
// Australia and this case names its state on purpose. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "open-a-project-trust-account-under-the-building-industry-fairness-act",
  order: 1656,
  region: "AU",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "subcontractor"],
  roles: ["finance-manager", "accountant", "commercial-manager", "contract-administrator"],
  stage: "build",
  icon: "Landmark",
  titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.title",
  titleDefault: "Open a project trust account under the Building Industry Fairness Act",
  descKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.desc",
  descDefault:
    "Work out whether the Queensland contract is one that needs a project trust, open the accounts and give the notices, tell every subcontractor they are a beneficiary, put cash retention into the retention trust, pay from the trust in the order the Act sets and keep the records the account review will ask for.",
  longDescKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.longdesc",
  longDescDefault:
    "Security of payment in Australia is state law, and Queensland went further than anyone else by putting the money itself into trust rather than only regulating the claims made against it. Under the Building Industry Fairness (Security of Payment) Act 2017 the head contractor on an eligible contract becomes a trustee: project payments come into a project trust account, cash retention sits in a retention trust account, and the subcontractors are beneficiaries with a right to be told about the trust and to see the records. That changes what a commercial team does day to day far more than the payment claim rules ever did, because a trustee who pays the wrong party out of the wrong account has not made a bookkeeping error, and the obligations bite whether or not anybody is in dispute.",
  estMinutes: 16,
  steps: [
    {
      id: "eligibility",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.in.contract", label: "The contract as signed" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.in.parties", label: "Who the parties are" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.out.decision", label: "Whether a trust is required" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.out.trustee", label: "Who the trustee is" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.title",
      titleDefault: "Settle whether this contract needs a trust",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.what",
      whatDefault:
        "Record against the contract whether it is an eligible contract for a project trust under the Queensland Act: what kind of work it is, what it is worth, who the contracting party is and whether the contract engages subcontractors at all. Record who the trustee is, which on a project trust is the contracted party, normally the head contractor.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.eligibility.why",
      whyDefault:
        "The eligibility test has been widened in stages, so a company that correctly decided last year that a job was out of scope can be wrong about the same kind of job this year. The decision belongs on the contract record with the reasons, because the question comes back at the first audit and nobody remembers what was assumed.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "open",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.in.decision", label: "Whether a trust is required" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.in.bank", label: "Bank that offers trust accounts" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.out.accounts", label: "Trust accounts opened" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.out.notices", label: "Notices given on time" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.title",
      titleDefault: "Open the accounts and give the notices",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.what",
      whatDefault:
        "Open the project trust account with a financial institution that offers them, name it so it reads as a trust account, and give the notices the Act requires within the periods it sets: to the commission, to the contracting party and to each beneficiary. Record the date each notice went and to whom.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.open.why",
      whyDefault:
        "The notices are where this regime is most often breached, because opening an account feels like the task and telling people about it feels like paperwork. The Act treats them as the substance: a trust nobody was told about protects nobody, and the penalty attaches to the notice rather than to the money.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "beneficiaries",
      icon: "Users",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.in.subcontracts", label: "Subcontracts let" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.in.new", label: "Subcontractors added later" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.out.register", label: "Beneficiary register" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.out.told", label: "Each one told they are one" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.title",
      titleDefault: "Keep the beneficiary register current",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.what",
      whatDefault:
        "Treat the subcontractor directory as the beneficiary register: every subcontractor engaged under the contract is a beneficiary of the project trust, and each new one has to be told after they are engaged rather than at the next convenient moment.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.beneficiaries.why",
      whyDefault:
        "A beneficiary can ask to see the trust records, and the obligation to tell them is triggered by the engagement, not by the first payment. A register that is a month behind the site is a register that has already missed a notice, and the subcontractors added late in a job are exactly the ones added under pressure.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "retention",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.in.withheld", label: "Cash retention withheld" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.in.terms", label: "Release terms per subcontract" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.out.trust", label: "Retention in the retention trust" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.out.dates", label: "Release dates per subcontractor" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.title",
      titleDefault: "Put the cash retention where the Act puts it",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.what",
      whatDefault:
        "Deposit cash retention withheld from a subcontractor into the retention trust account rather than into working capital, and hold the balance per subcontractor with the date each part of it falls due for release. One retention trust account serves the trustee across its contracts, so the per subcontractor balance has to be readable inside it.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.retention.why",
      whyDefault:
        "Retention used as working capital is the practice the whole trust framework was built to end, and it is also the practice that collapses a chain of subcontractors when a builder fails. Held in trust with a release date per subcontractor, the money is theirs and the release is something the calendar produces rather than something a subcontractor has to ask for twice.",
      moduleLabel: "Retention",
      moduleLabelKey: "finance.retention_tab",
      to: "/projects/:projectId/finance?tab=retention",
    },
    {
      id: "pay",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.in.received", label: "Project payment received" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.in.due", label: "Subcontractor amounts due" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.out.paid", label: "Beneficiaries paid from the trust" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.out.own", label: "Trustee's own money taken last" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.title",
      titleDefault: "Pay from the trust, and pay yourself out of it last",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.what",
      whatDefault:
        "Run every payment to a beneficiary out of the project trust account, and withdraw the trustee's own entitlement from the same account only after the beneficiaries for that payment have been dealt with. Keep the payment record so each withdrawal can be traced to the amount it discharged.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.pay.why",
      whyDefault:
        "A trustee paying itself ahead of its beneficiaries is the failure the Act is aimed at, and it looks completely ordinary from inside a busy accounts department. The order matters more than the amount, which is why the sequence has to be built into how payments are run rather than checked afterwards.",
      moduleLabel: "Payments",
      moduleLabelKey: "finance.payments",
      to: "/projects/:projectId/finance?tab=payments",
    },
    {
      id: "records",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.in.ledger", label: "Trust account movements" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.in.statements", label: "Bank statements" },
      ],
      outputs: [
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.out.review", label: "Monthly account review" },
        { labelKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.out.records", label: "Trust records ready to produce" },
      ],
      titleKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.title",
      titleDefault: "Review the account every month and keep the records",
      whatKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.what",
      whatDefault:
        "Reconcile the trust account against the bank statement each month, keep the trust ledger, the notices given and the records of every deposit and withdrawal, and hold them for the period the Act requires so they can be produced to the commission or to a beneficiary who asks.",
      whyKey: "cases.open_a_project_trust_account_under_the_building_industry_fairness_act.step.records.why",
      whyDefault:
        "The account review is not an audit of whether the business is solvent, it is a check that the trust was operated as a trust, and it is answered entirely out of records that either exist or do not. A month reconciled at the time takes twenty minutes; the same month reconstructed under a request takes days and still looks reconstructed.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
