// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Adopt a CDE approval preset".
//
// A short, focused worked example for the CDE setup wizard and the
// ready-made ISO 19650 approval presets: run the wizard, adopt a preset in
// one click, tailor the cloned route, then confirm the go-live gate is
// actually satisfied before the whole team is invited on.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "adopt-a-cde-approval-preset",
  order: 1036,
  category: "bim",
  companyTypes: ["general-contractor", "bim-consultant", "project-manager"],
  roles: ["bim-coordinator", "document-controller", "project-manager"],
  stage: "plan",
  icon: "ShieldCheck",
  titleKey: "cases.adopt_a_cde_approval_preset.title",
  titleDefault: "Adopt a CDE approval preset",
  descKey: "cases.adopt_a_cde_approval_preset.desc",
  descDefault:
    "Run the CDE setup wizard, adopt a ready-made ISO 19650 review flow in one click, tailor it to your team, then confirm the go-live gate is actually satisfied.",
  longDescKey: "cases.adopt_a_cde_approval_preset.longdesc",
  longDescDefault:
    "A CDE gate is only as good as the review flow behind it. Rather than building an approval route from a blank form, start from a ready-made ISO 19650 preset, adopt it into your project as an editable route, and tune it before real work runs through it.",
  estMinutes: 8,
  steps: [
    {
      id: "run-wizard",
      icon: "Gauge",
      inputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.run-wizard.in.team",
          label: "Project team",
        },
      ],
      outputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.run-wizard.out.roles",
          label: "Role assignments",
        },
      ],
      titleKey: "cases.adopt_a_cde_approval_preset.step.run-wizard.title",
      titleDefault: "Run the CDE setup wizard",
      whatKey: "cases.adopt_a_cde_approval_preset.step.run-wizard.what",
      whatDefault:
        "Open Set up CDE and step through the naming convention, suitability codes and the four functional roles - Author, Reviewer, Approver, Viewer.",
      whyKey: "cases.adopt_a_cde_approval_preset.step.run-wizard.why",
      whyDefault:
        "The wizard is resumable and saves as you go, so a half-finished setup never loses progress. Fixing who holds each role first is what makes the gate a step later mean something.",
      moduleLabel: "Common Data Environment",
      moduleLabelKey: "cde.title",
      to: "/projects/:projectId/cde",
    },
    {
      id: "adopt-preset",
      icon: "Workflow",
      inputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.adopt-preset.in.roles",
          label: "Role assignments",
        },
      ],
      outputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.adopt-preset.out.route",
          label: "Editable review route",
        },
      ],
      titleKey: "cases.adopt_a_cde_approval_preset.step.adopt-preset.title",
      titleDefault: "Adopt an approval preset",
      whatKey: "cases.adopt_a_cde_approval_preset.step.adopt-preset.what",
      whatDefault:
        "In the CDE page's Approval presets card, pick Issue for review, Comment and return, or Review and publish, and click Adopt. This clones the preset into a route that belongs to your project.",
      whyKey: "cases.adopt_a_cde_approval_preset.step.adopt-preset.why",
      whyDefault:
        "The tenant-wide preset stays read-only and reusable by every other project; adopting makes your own copy the one you can actually change, without anyone else's flow moving under them.",
      moduleLabel: "Common Data Environment",
      moduleLabelKey: "cde.title",
      to: "/projects/:projectId/cde",
    },
    {
      id: "tailor-route",
      icon: "Pencil",
      inputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.tailor-route.in.route",
          label: "Editable review route",
        },
      ],
      outputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.tailor-route.out.tuned",
          label: "Tuned review route",
        },
      ],
      titleKey: "cases.adopt_a_cde_approval_preset.step.tailor-route.title",
      titleDefault: "Tailor the route to your team",
      whatKey: "cases.adopt_a_cde_approval_preset.step.tailor-route.what",
      whatDefault:
        "In Approval routes, open your cloned route and adjust it: rename it, change an approver's role, add a second step, or set an SLA - then dry-run it before anyone routes real work through it.",
      whyKey: "cases.adopt_a_cde_approval_preset.step.tailor-route.why",
      whyDefault:
        "A preset is a starting point, not a straitjacket. The dry run proves your tailored route still terminates at approved before it gates a real container.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "confirm-gate",
      icon: "CheckCircle2",
      inputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.confirm-gate.in.tuned",
          label: "Tuned review route",
        },
      ],
      outputs: [
        {
          labelKey: "cases.adopt_a_cde_approval_preset.step.confirm-gate.out.ready",
          label: "Go-live readiness",
        },
      ],
      titleKey: "cases.adopt_a_cde_approval_preset.step.confirm-gate.title",
      titleDefault: "Confirm the go-live gate",
      whatKey: "cases.adopt_a_cde_approval_preset.step.confirm-gate.what",
      whatDefault:
        "Back in the CDE page, check the go-live readiness scorecard. It only allows inviting the whole team once the workflow has actually been exercised, not just configured on paper.",
      whyKey: "cases.adopt_a_cde_approval_preset.step.confirm-gate.why",
      whyDefault:
        "A CDE that looks configured but has never moved a container through its gates is a showroom, not a working environment. The gate is what stops a team finding that out the hard way.",
      moduleLabel: "Common Data Environment",
      moduleLabelKey: "cde.title",
      to: "/projects/:projectId/cde",
    },
  ],
};

export default playbook;
