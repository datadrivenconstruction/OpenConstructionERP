// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Reconcile materials on form M-29" (RU).
//
// Derive the normative material requirement from the norms and the work actually
// completed, set it against what the store really issued, separate allowed losses
// from real overrun, get every overrun explained and signed for, and close the
// month cumulatively. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "reconcile-materials-on-form-m-29",
  order: 1306,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor"],
  roles: ["site-manager", "foreman", "estimator", "accountant"],
  region: "RU",
  icon: "Container",
  titleKey: "cases.reconcile_materials_on_form_m_29.title",
  titleDefault: "Reconcile materials on form M-29",
  descKey: "cases.reconcile_materials_on_form_m_29.desc",
  descDefault:
    "Take the norm consumption for the work the month actually completed, set it against what the store really issued, separate allowed losses from real overrun, get each overrun explained in writing and close the month with the cumulative position.",
  longDescKey: "cases.reconcile_materials_on_form_m_29.longdesc",
  longDescDefault:
    "M-29 is the monthly report in which a Russian site states how much material the norms allowed for the work it completed and how much it actually used. It is the classic place a job loses money invisibly: material is usually the largest single share of the cost, and an overrun of a few percent, repeated every month across a dozen positions, never appears as an event anybody reacts to. The form exists to force the comparison and to make somebody sign for the difference, which is why an overrun on it has to be explained and accepted rather than quietly absorbed.",
  estMinutes: 14,
  steps: [
    {
      id: "norms",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.norms.in.positions", label: "Positions in the report" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.norms.in.norms", label: "Norm consumption per unit" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.norms.out.requirement", label: "Normative requirement" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.norms.out.substitutions", label: "Substituted materials converted" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.norms.title",
      titleDefault: "Take the norm consumption for the work you are reporting",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.norms.what",
      whatDefault:
        "For each position in the report, take the material consumption the norm fixes per unit of measure, and note which material the norm actually names, because anything substituted on site has to be converted to the normed material before it can be compared at all.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.norms.why",
      whyDefault:
        "The first section of M-29 is the normative requirement, and it is derived rather than stated: the quantity of work multiplied by the norm per unit. Taking it from the norm instead of from last month's figure is the whole reason the comparison means anything.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "waste",
      icon: "Split",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.waste.in.materials", label: "Materials in scope" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.waste.in.delivery", label: "Delivery and cutting form" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.waste.out.allowance", label: "Allowed loss per material" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.waste.out.purchase", label: "Purchase quantity explained" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.waste.title",
      titleDefault: "Separate the losses the norm allows from real overrun",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.waste.what",
      whatDefault:
        "Set the allowance for trimming, offcuts, breakage and transport loss for each material, so the difference between what was purchased and what was built into the work reads as a known figure rather than as an unexplained gap.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.waste.why",
      whyDefault:
        "Part of the difference between norm and actual is not overrun: it is loss the norm already contemplates or that the delivered form of the material imposes. Mixing the two makes every position look like a problem, and a report in which everything is a problem stops being read.",
      moduleLabel: "Waste Factors",
      moduleLabelKey: "nav.waste_factors",
      to: "/waste-factors",
    },
    {
      id: "work",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.work.in.measure", label: "Measurement on site" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.work.in.units", label: "Units the smeta uses" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.work.out.volume", label: "Volume completed this month" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.work.out.agreed", label: "Same figure as the acceptance act" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.work.title",
      titleDefault: "Fix the volume of work the month actually completed",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.work.what",
      whatDefault:
        "Record the quantity of each type of work completed in the reporting month, measured in the same units and by the same rule the smeta uses, because this quantity is what the whole normative requirement is calculated from.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.work.why",
      whyDefault:
        "M-29 compares consumption against the norm for the work done, not for the work planned. An overstated volume hides a material overrun completely, which is exactly why the same measurement has to feed both the KS-2 act and this report rather than being produced twice.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "actual",
      icon: "Warehouse",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.actual.in.deliveries", label: "Deliveries booked in" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.actual.in.issues", label: "Issues to each position" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.actual.out.consumed", label: "Actual consumption" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.actual.out.stock", label: "Closing stock counted" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.actual.title",
      titleDefault: "Record what was really issued and consumed",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.actual.what",
      whatDefault:
        "Book the deliveries in, the issues out against each work position and the returns, then close the month with a physical stock check, so consumption means what left the store for that work rather than what was bought during the month.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.actual.why",
      whyDefault:
        "Purchased is not consumed. Material standing on site at the end of the month belongs to the next report, and treating a delivery as consumption produces an alarming overrun in one month and an impossible saving in the following one, which is how the report loses its credibility.",
      moduleLabel: "Site Inventory",
      moduleLabelKey: "site_inventory.title",
      to: "/projects/:projectId/site-inventory",
    },
    {
      id: "variance",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.variance.in.requirement", label: "Normative requirement" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.variance.in.consumed", label: "Actual consumption" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.variance.out.variance", label: "Variance per position" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.variance.out.money", label: "Variance in money" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.variance.title",
      titleDefault: "Compare actual against norm position by position",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.variance.what",
      whatDefault:
        "Set the actual consumption against the normative requirement for each material and each position: the post-calculation reads the material money the estimate allowed against what the store issued for the quantity installed, line by line, and the stock ledger behind it gives the physical difference per material. Sort the result by money rather than by percentage.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.variance.why",
      whyDefault:
        "The second section of M-29 is exactly this comparison, and its value lies in being read by position. One concrete or reinforcement line can carry more overrun in roubles than every other position together, while a cheap material with a dramatic percentage swing costs almost nothing and pulls the whole discussion away from where the money went.",
      moduleLabel: "Post-calculation",
      moduleLabelKey: "postcalc.title",
      to: "/projects/:projectId/postcalc",
    },
    {
      id: "explain",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.explain.in.overruns", label: "Overruns above threshold" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.explain.in.reasons", label: "Written reason from the site" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.explain.out.accepted", label: "Accepted explanations" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.explain.out.rejected", label: "Rejected and referred on" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.explain.title",
      titleDefault: "Get every overrun explained and signed for",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.explain.what",
      whatDefault:
        "Route each overrun above the agreed threshold to the person who has to explain it, with the reason written down, and on to the person who has to accept or refuse that explanation. Keep the refused ones visible rather than closing them.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.explain.why",
      whyDefault:
        "An overrun on M-29 is not written off by the site that caused it. The form is drawn up by the site manager, checked by the production and technical department and approved by the chief engineer, and that approval is what turns a number into either an accepted cost or a matter for recovery. Without a route, the explanation is a corridor conversation that nobody can produce six months later.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "report",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.report.in.variance", label: "Variance with explanations" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.report.in.prior", label: "Position from previous months" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.report.out.form", label: "Signed report for the month" },
        { labelKey: "cases.reconcile_materials_on_form_m_29.step.report.out.cumulative", label: "Cumulative position" },
      ],
      titleKey: "cases.reconcile_materials_on_form_m_29.step.report.title",
      titleDefault: "Close the month with the cumulative position",
      whatKey: "cases.reconcile_materials_on_form_m_29.step.report.what",
      whatDefault:
        "Issue the report with both sections, the normative requirement and the comparison against actual, with the explanations attached, and show the position from the start of the job next to the position for the month.",
      whyKey: "cases.reconcile_materials_on_form_m_29.step.report.why",
      whyDefault:
        "A single month is noise, the cumulative line is the finding. A position running three percent over every month for six months is invisible monthly and unmistakable cumulatively, and that cumulative figure is also what reconciles against the material cost the estimate budgeted in the first place.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
