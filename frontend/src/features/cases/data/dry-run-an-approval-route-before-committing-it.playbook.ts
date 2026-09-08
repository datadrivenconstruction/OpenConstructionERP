// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Dry-run an approval route before committing it".
//
// Start from a tenant-wide preset, simulate the route to see where each step
// lands and whether it can ever reach approved, fix what the dry run exposes,
// then commit it and watch it work. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "dry-run-an-approval-route-before-committing-it",
  order: 1046,
  category: "quality",
  companyTypes: ["general-contractor", "project-manager", "bim-consultant"],
  roles: ["document-controller", "project-manager"],
  stage: "plan",
  icon: "Workflow",
  titleKey: "cases.dry_run_an_approval_route_before_committing_it.title",
  titleDefault: "Dry-run an approval route before committing it",
  descKey: "cases.dry_run_an_approval_route_before_committing_it.desc",
  descDefault:
    "Build a review route from a preset, dry-run it to see which role each step lands on and whether it can ever reach approved, fix what the simulation exposes, and only then put it to work.",
  longDescKey: "cases.dry_run_an_approval_route_before_committing_it.longdesc",
  longDescDefault:
    "An approval route that cannot terminate is invisible until a real document is stuck in it, and by then the gate it was protecting has already slipped. This case starts from a tenant-wide review preset instead of a blank form, walks the route in a simulator that shares its clearing logic with the live engine, so the dry run cannot drift from what the workflow will actually do, and only commits it once it has been proved to reach approved.",
  estMinutes: 8,
  steps: [
    {
      id: "preset",
      icon: "Workflow",
      inputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.preset.in.presets",
          label: "Tenant-wide preset library",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.preset.in.kind",
          label: "What needs reviewing",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.preset.out.route",
          label: "Editable route of your own",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.preset.out.steps",
          label: "Steps and approver roles",
        },
      ],
      titleKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.preset.title",
      titleDefault: "Start from a preset",
      whatKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.preset.what",
      whatDefault:
        "Open the route library and pick the review preset closest to the flow you need rather than starting from a blank form. Adopting one clones it into a route you own and can edit; the preset itself stays read-only.",
      whyKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.preset.why",
      whyDefault:
        "Routes drawn from scratch tend to encode one person's habits and one project's politics, and they leave out the review step nobody remembers until an auditor asks. Cloning rather than editing in place also means tuning yours cannot silently move the flow every other project is already running.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "simulate",
      icon: "Gauge",
      inputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.simulate.in.route",
          label: "Draft route",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.simulate.in.roles",
          label: "Who actually holds each role",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.simulate.out.walk",
          label: "Step-by-step walk",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.simulate.out.outcome",
          label: "Approved, rejected or stuck",
        },
      ],
      titleKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.simulate.title",
      titleDefault: "Dry-run it and read where it lands",
      whatKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.simulate.what",
      whatDefault:
        "Simulate the route before anything real touches it. The dry run walks the steps in order and reports, for each one, which role or named person the decision falls to, how many approvals it takes to clear, and where the whole thing ends up.",
      whyKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.simulate.why",
      whyDefault:
        "A step set to all against a role with one member behaves nothing like the same step once that role has four. Reading the walk is the only way to see the real shape of a flow without discovering it on a live document in the week it matters.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "fix",
      icon: "Pencil",
      inputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.fix.in.warnings",
          label: "Warnings from the walk",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.fix.in.scenario",
          label: "A rejection worth testing",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.fix.out.tuned",
          label: "Tuned route",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.fix.out.proved",
          label: "Route proved to terminate",
        },
      ],
      titleKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.fix.title",
      titleDefault: "Fix what the dry run exposes",
      whatKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.fix.what",
      whatDefault:
        "Work the warnings: a quorum higher than the role can ever supply, a step that needs several approvers when only one exists, a route that never reaches approved. Then run the what-if walk, put a rejection on the step you are least sure of, and see whether the route dies there or carries on.",
      whyKey: "cases.dry_run_an_approval_route_before_committing_it.step.fix.why",
      whyDefault:
        "The stuck step is the one that hurts, because nothing fails visibly. A document simply sits in review until somebody thinks to ask why, and the answer is always that the route was never walked. Finding it in a simulation costs a minute, finding it the week before a gate costs the gate.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "commit",
      icon: "CheckCircle2",
      inputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.commit.in.route",
          label: "Proved route",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.commit.in.work",
          label: "Real work to route",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.commit.out.live",
          label: "Live approvals in flight",
        },
        {
          labelKey:
            "cases.dry_run_an_approval_route_before_committing_it.step.commit.out.held",
          label: "Held time per step",
        },
      ],
      titleKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.commit.title",
      titleDefault: "Commit it and watch it run",
      whatKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.commit.what",
      whatDefault:
        "Save the tuned route and start putting real work through it, then move off the templates tab: running and history shows every instance against the route and where each one is sitting, and the analytics show how long each step and each role is actually holding things.",
      whyKey:
        "cases.dry_run_an_approval_route_before_committing_it.step.commit.why",
      whyDefault:
        "A route that terminates in a simulation can still take three weeks in practice, and the held time per step is the only honest read on whether the approver you picked has the capacity to be one. The same record is what proves, a year later, that the thing that got approved went through the route everybody agreed to rather than a nod in a corridor.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
  ],
};

export default playbook;
