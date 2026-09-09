// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Hold retention money on trust under the Construction Contracts Act" (NZ).
//
// The party that WITHHOLDS retention money in New Zealand is a trustee of it,
// and has been automatically since the Construction Contracts (Retention Money)
// Amendment Act 2023. This case is the custody side of the payment regime, not
// the claim side: where the money sits, what records make it identifiable, and
// who has to be told what is being held from them. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "hold-retention-money-on-trust-under-the-construction-contracts-act",
  order: 1400,
  region: "NZ",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "cost-consultant"],
  roles: ["commercial-manager", "contract-administrator", "accountant", "finance-manager"],
  icon: "KeyRound",
  titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.title",
  titleDefault: "Hold retention money on trust under the Construction Contracts Act",
  descKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.desc",
  descDefault:
    "Record what the contract lets you retain, withhold it as a named line, put it where the Act requires it to sit, keep the ledger that makes each subcontractor's share identifiable, report it to the party it is held from and release it on the date the contract sets.",
  longDescKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.longdesc",
  longDescDefault:
    "Retention money withheld under a commercial construction contract is not your money and has not been since the retentions regime was written into the Construction Contracts Act 2002. The Construction Contracts (Retention Money) Amendment Act 2023 went further and made the trust automatic: it exists from the moment the money is withheld, whether or not the party holding it does anything to create it. From that point the money has to sit in a bank account used only for retention money, or be covered by a complying instrument such as a financial guarantee or an insurance policy, it cannot be used as working capital, the accounting records have to show whose money each dollar is, and the party it is held from has to be told. Failing any of that is an offence rather than a commercial argument, and the directors of the company are exposed personally. None of it is difficult; all of it is a records discipline that has to run every month rather than be assembled at the end.",
  estMinutes: 14,
  steps: [
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.in.contract",
          label: "Signed subcontract",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.in.schedule",
          label: "Retention terms as written",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.out.rate",
          label: "Retention rate and cap on record",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.out.release",
          label: "Release trigger and dates",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.title",
      titleDefault: "Record what the contract actually lets you retain",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.what",
      whatDefault:
        "Take the retention terms off the subcontract and record them where the people who compute payments can read them: the percentage, the maximum the contract caps retention at, what event releases the first half, what event releases the balance, and the date the contract was signed or last renewed. Record as well whether this is a commercial construction contract, because the retentions regime reaches those and not a residential occupier's own contract.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.terms.why",
      whyDefault:
        "The signature date decides which version of the rules applies, and that is not a detail. Contracts entered into or renewed from 5 October 2023 sit under the automatic trust and the reporting duty the amendment introduced, while older ones sit under the lighter 2017 regime. A company running one process for a book of contracts written under both is complying with whichever one it happened to build its spreadsheet around.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "withhold",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.in.claim",
          label: "Subcontractor payment claim",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.in.rate",
          label: "Retention rate and cap on record",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.out.line",
          label: "Retention shown as its own line",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.out.net",
          label: "Net amount scheduled for payment",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.title",
      titleDefault: "Withhold it as a line, not as a smaller total",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.what",
      whatDefault:
        "When you schedule a subcontractor's payment, take the retention as a separate deduction line carrying the period it relates to and the cumulative amount now held, and let the net figure fall out of it. Stop deducting once the cumulative total reaches the contract cap rather than continuing at the percentage.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.withhold.why",
      whyDefault:
        "A retention that exists only as the difference between two totals cannot be traced, and the whole regime rests on the money being identifiable as somebody else's. It is also the point at which the trust starts, so the day this line is created is the day the duties attach. A payer who cannot say which line created the trust is a payer who cannot show when the reporting clock began.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "trust",
      icon: "Landmark",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.in.line",
          label: "Retention shown as its own line",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.in.account",
          label: "Trust account or complying instrument",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.out.ledger",
          label: "Ledger of who holds what",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.out.balance",
          label: "Balance held per subcontractor",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.title",
      titleDefault: "Put the money where the Act says it has to sit",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.what",
      whatDefault:
        "Post each withheld amount to the retention ledger against the subcontractor it belongs to, and record which bank account it is held in or which complying instrument covers it. The account has to be used only for retention money, and the ledger has to name the party, the amount, the contract and the date it was withheld.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.trust.why",
      whyDefault:
        "The 2023 amendment makes this money trust money automatically, which means it is outside the reach of your own creditors if the company fails, but only to the extent it can be identified. Money mixed into the working account and spent as float is money a liquidator will treat as yours, and the subcontractors it belonged to join the queue with everyone else. Using retention money as working capital is also an offence in itself.",
      moduleLabel: "Retention",
      moduleLabelKey: "finance.retention_tab",
      to: "/projects/:projectId/finance?tab=retention",
    },
    {
      id: "evidence",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.in.ledger",
          label: "Ledger of who holds what",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.in.statements",
          label: "Bank statements and instrument",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.out.pack",
          label: "Custody evidence filed",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.out.trail",
          label: "Audit trail per period",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.title",
      titleDefault: "File the evidence that the money is where you say",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.what",
      whatDefault:
        "Keep the bank statement for the retention account for every period alongside the ledger it should agree with, and file the complying instrument itself where retention is covered by a guarantee or a policy rather than by cash. Keep the instrument's expiry date visible, because an expired guarantee leaves the money uncovered while the ledger still says it is fine.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.evidence.why",
      whyDefault:
        "A ledger is an assertion and a bank statement is evidence, and the difference matters on the one day anyone asks. The regulator, an insolvency practitioner and a subcontractor's solicitor all ask the same question in the same order: what is held, where is it, and show me. Answering it takes minutes if the two documents were filed together each month and weeks if they were not.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "report",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.in.balance",
          label: "Balance held per subcontractor",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.in.period",
          label: "Reporting period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.out.sent",
          label: "Retention report sent",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.out.record",
          label: "Proof of what was sent and when",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.title",
      titleDefault: "Tell each party what you are holding from them",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.what",
      whatDefault:
        "Send each subcontractor a report of the retention money held from them: the amount, the date it was withheld, where it is held or what instrument covers it, and how the total moved since the last report. Do it as soon as practicable after retention is first withheld from them and then on a regular cycle of no more than three months, and keep the sent copy against the contract.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.report.why",
      whyDefault:
        "This duty is the part of the regime most often missed, because nothing on site stops when it is skipped and no subcontractor chases a report they have never seen. It is still an obligation with an offence behind it, and the reports are also the cheapest defence there is: a party who has been told the same figure every quarter does not open the final account arguing about what was held.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "release",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.in.trigger",
          label: "Release trigger and dates",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.in.defects",
          label: "Defects position",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.out.dates",
          label: "Release dates under watch",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.out.warning",
          label: "Warning before each release",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.title",
      titleDefault: "Tie each release to the defects period that triggers it",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.what",
      whatDefault:
        "Hold each subcontractor's retention against the defects liability period it is released by: the first half at practical completion and the balance when the period ends. Where a release is being held back, record the defect it is held against, who owes the fix and by when, rather than letting the date pass in silence.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.release.why",
      whyDefault:
        "The release trigger is not a date somebody typed in, it is the end of a period that the defects record already tracks, so keeping the two apart is how a retention gets held for a year after the obligation it secured expired. A held release with a named defect against it is a commercial position. A held release with nothing against it is trust money that should have gone back, and a subcontractor can put that straight into adjudication.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "reconcile",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.in.ledger",
          label: "Ledger of who holds what",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.in.bank",
          label: "Retention account balance",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.out.gap",
          label: "Shortfall named if there is one",
        },
        {
          labelKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.out.report",
          label: "Retention position across projects",
        },
      ],
      titleKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.title",
      titleDefault: "Reconcile the ledger against the account every period",
      whatKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.what",
      whatDefault:
        "Read the total the ledger says is held against the balance the account actually carries, across every project at once, and name the difference if there is one. Do it on the same day each period rather than when somebody asks.",
      whyKey: "cases.hold_retention_money_on_trust_under_the_construction_contracts_act.step.reconcile.why",
      whyDefault:
        "A shortfall between the ledger and the account is the one number in this whole case that cannot be argued about, and it grows quietly: a release paid from the working account, a deduction never banked, a project closed without its balance moving. Found in the month it happens it is a transfer. Found at liquidation it is the evidence in somebody else's case.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
