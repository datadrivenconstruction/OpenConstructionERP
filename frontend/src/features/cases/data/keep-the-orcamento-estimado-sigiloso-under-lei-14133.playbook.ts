// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep the orcamento estimado sigiloso under Lei 14.133" (BR).
//
// Article 24 of Lei 14.133/2021 lets a contracting body keep the estimated
// budget confidential where it justifies doing so, while still publishing the
// quantities and everything else a bidder needs in order to price. So the
// deliverable is two documents out of one estimate, and a disclosure date that
// somebody owns. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-the-orcamento-estimado-sigiloso-under-lei-14133",
  order: 1506,
  region: "BR",
  category: "tendering",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  roles: ["procurement-buyer", "estimator", "contract-administrator"],
  icon: "KeyRound",
  titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.title",
  titleDefault: "Keep the orcamento estimado sigiloso under Lei 14.133",
  descKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.desc",
  descDefault:
    "Build the orcamento estimado, decide and justify whether it is confidential, publish the quantitativos without the prices, keep the priced version behind access control and disclose it on the date the law requires with the date on the record.",
  longDescKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.longdesc",
  longDescDefault:
    "Article 24 of Lei 14.133 of 2021 allows the estimated budget to be confidential where the contracting body justifies it, and it is explicit that confidentiality covers the prices and not the rest: the quantities and the information a bidder needs in order to prepare a proposal are published either way. That single sentence is the whole design of this case. One estimate has to produce two documents, an unpriced one that goes out with the edital and a priced one that a named group can open, and the second one has to become public at the moment the law says rather than when somebody remembers. A confidential budget that leaks is a cancelled procedure; a confidential budget that is never disclosed is a finding of a different kind, and the second is far more common because nothing at all happens on the day it was due.",
  estMinutes: 14,
  steps: [
    {
      id: "estimate",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.in.design",
          label: "Design and its quantities",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.in.base",
          label: "Reference price base",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.out.priced",
          label: "Priced orcamento estimado",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.out.quant",
          label: "Quantitativos per item",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.title",
      titleDefault: "Build the orcamento estimado in one place",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.what",
      whatDefault:
        "Price the whole scope in the bill, with quantities per item and a unit cost against each, so the priced and unpriced versions are two views of one document rather than two spreadsheets somebody keeps in step by hand.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.estimate.why",
      whyDefault:
        "The moment there are two files, one of them is out of date and nobody knows which. Bidders then price quantities that the confidential estimate no longer contains, and the difference surfaces at the first medicao as work that was never in anybody's proposal.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "decide",
      icon: "Gavel",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.in.mode",
          label: "Procurement route chosen",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.in.priced",
          label: "Priced orcamento estimado",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.out.decision",
          label: "Confidentiality decision recorded",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.out.reason",
          label: "Justification on the record",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.title",
      titleDefault: "Decide sigilo, and write down why",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.what",
      whatDefault:
        "Settle whether this procedure runs with a confidential estimate, write the justification into the tender record before the edital is published, and name the officers who may see the priced version. Note the moment at which it becomes public, because that is a term of the decision and not an afterthought.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.decide.why",
      whyDefault:
        "Article 24 of Lei 14.133 of 2021 makes confidentiality conditional on a justification, so an estimate withheld without one is simply an estimate that was not published. Deciding before the edital also settles the question for everybody at once, instead of leaving each person to guess what may be sent to a bidder who asks.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "split",
      icon: "FileOutput",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.in.quant",
          label: "Quantitativos per item",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.in.decision",
          label: "Confidentiality decision recorded",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.out.export",
          label: "Unpriced bill for the edital",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.out.check",
          label: "Report checked for stray prices",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.title",
      titleDefault: "Publish the quantitativos without the prices",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.what",
      whatDefault:
        "Export the bill with the items, the units and the quantities and without any cost column, then read the export itself before it goes out. Check the totals row, the group subtotals and any figure carried in a note, because those are where a price survives an unpriced export.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.split.why",
      whyDefault:
        "Confidentiality under Lei 14.133 of 2021 covers the prices, not the quantities, so an edital that publishes neither is not more careful, it is defective: bidders cannot price work whose extent they have not been told. And a single surviving subtotal defeats the whole decision, because the unit cost can be inferred from it.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
    {
      id: "control",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.in.priced",
          label: "Priced orcamento estimado",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.in.named",
          label: "Officers named on the decision",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.out.filed",
          label: "Priced version filed with access limited",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.out.log",
          label: "Access log kept",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.title",
      titleDefault: "Keep the priced version where only named people reach it",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.what",
      whatDefault:
        "File the priced estimate in the document register with access limited to the officers the decision names, and let the system record who opened it and when. Do not circulate it by email, because an attachment forwarded once is outside every control you have.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.control.why",
      whyDefault:
        "If the estimate does leak, the question that follows is not whether it leaked but who could have seen it, and the answer has to be a list rather than a guess. A folder with a named group and an access log answers it in a minute; a file that lived in six mailboxes cannot be answered at all, and the procedure is cancelled while nobody is proved to have done anything.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "receive",
      icon: "FileInput",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.in.export",
          label: "Unpriced bill for the edital",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.in.bids",
          label: "Proposals received",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.out.compare",
          label: "Bid comparison against the estimate",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.out.outliers",
          label: "Items priced far from the estimate",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.title",
      titleDefault: "Compare the proposals against the estimate nobody saw",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.what",
      whatDefault:
        "Load the proposals against the same item list and read them item by item rather than on the total alone. Look for the positions priced far below the estimate as well as far above, and ask what the bidder thinks the item contains.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.receive.why",
      whyDefault:
        "A confidential estimate makes the comparison worth doing, because the prices were formed without sight of it and a wide spread on one item means the item is ambiguous rather than that one bidder is careless. That is the reading that improves the next edital, and it is only available before the estimate is disclosed.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "disclose",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.in.decision",
          label: "Confidentiality decision recorded",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.in.priced",
          label: "Priced orcamento estimado",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.out.published",
          label: "Estimate published to the file",
        },
        {
          labelKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.out.date",
          label: "Disclosure date on the record",
        },
      ],
      titleKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.title",
      titleDefault: "Disclose it when the law says, and record the date",
      whatKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.what",
      whatDefault:
        "Release the priced estimate into the procurement record at the point the decision named, log the release in the correspondence file, and lift the access restriction so nobody has to ask. Say plainly which version was released, by reference rather than by description.",
      whyKey: "cases.keep_the_orcamento_estimado_sigiloso_under_lei_14133.step.disclose.why",
      whyDefault:
        "Confidentiality under Lei 14.133 of 2021 is temporary by design, and the failure is almost always inertia rather than intent: the procedure ends, the folder stays closed and nobody is watching a date that produces no event. Logging the release makes the end of the confidentiality as visible as its beginning, which is the part an audit asks about.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
  ],
};

export default playbook;
