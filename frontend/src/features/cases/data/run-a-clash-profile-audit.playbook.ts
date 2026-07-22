// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a clash profile audit".
//
// Define a clash profile - which element sets test against which, at what
// tolerance - run it against the federation, triage the hits down to the real
// clashes and push them out as issues. Content strings key plus inline default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-a-clash-profile-audit",
  order: 1016,
  category: "bim",
  companyTypes: ["bim-consultant", "general-contractor", "designer"],
  icon: "Crosshair",
  titleKey: "cases.run_a_clash_profile_audit.title",
  titleDefault: "Run a clash profile audit",
  descKey: "cases.run_a_clash_profile_audit.desc",
  descDefault:
    "Define a clash profile - which element sets test against which, and at what tolerance - run it against the federation, triage the hits down to the real clashes and push them out as issues to fix.",
  longDescKey: "cases.run_a_clash_profile_audit.longdesc",
  longDescDefault:
    "A naive clash run returns thousands of hits and buries the ten that matter. The skill is in the profile: pairing the right sets, setting a sensible tolerance and filtering the noise, so a review sees real coordination problems and not insulation brushing a wall.",
  estMinutes: 12,
  steps: [
    {
      id: "profile",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.profile.in.federation", label: "Federated model" },
        { labelKey: "cases.run_a_clash_profile_audit.step.profile.in.matrix", label: "Coordination matrix" },
      ],
      outputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.profile.out.profile", label: "Clash profile" },
      ],
      titleKey: "cases.run_a_clash_profile_audit.step.profile.title",
      titleDefault: "Define the clash profile",
      whatKey: "cases.run_a_clash_profile_audit.step.profile.what",
      whatDefault:
        "Set up the profile: which element sets test against which - ducts against structure, pipes against ducts - and the tolerance that counts as a real hit.",
      whyKey: "cases.run_a_clash_profile_audit.step.profile.why",
      whyDefault:
        "The profile decides whether the run is useful or noise. Pairing the right sets and setting a real tolerance is what keeps the result to clashes a person actually needs to resolve.",
      moduleLabel: "Clash Profiles",
      moduleLabelKey: "nav.clash_detection",
      to: "/clash/profiles",
    },
    {
      id: "run",
      icon: "Crosshair",
      inputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.run.in.profile", label: "Clash profile" },
      ],
      outputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.run.out.hits", label: "Clash results" },
      ],
      titleKey: "cases.run_a_clash_profile_audit.step.run.title",
      titleDefault: "Run it against the model",
      whatKey: "cases.run_a_clash_profile_audit.step.run.what",
      whatDefault:
        "Run the profile against the federated model and let it list every hit that breaks the tolerance you set, ready to be worked through.",
      whyKey: "cases.run_a_clash_profile_audit.step.run.why",
      whyDefault:
        "Running to a defined profile makes the result repeatable: the next run after a design update is comparable, so you can see whether coordination is getting better or worse.",
      moduleLabel: "Clash Detection",
      moduleLabelKey: "clash.title",
      to: "/clash",
    },
    {
      id: "triage",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.triage.in.hits", label: "Clash results" },
      ],
      outputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.triage.out.real", label: "Real clashes" },
      ],
      titleKey: "cases.run_a_clash_profile_audit.step.triage.title",
      titleDefault: "Triage the hits",
      whatKey: "cases.run_a_clash_profile_audit.step.triage.what",
      whatDefault:
        "Group the hits, drop the duplicates and the harmless brushes, and keep the genuine clashes that need a design change, so the review works a short real list.",
      whyKey: "cases.run_a_clash_profile_audit.step.triage.why",
      whyDefault:
        "A team that has to wade through a thousand false clashes stops reading the report. Triaging to the real ones is what keeps clash detection trusted rather than ignored.",
      moduleLabel: "Clash Detection",
      moduleLabelKey: "clash.title",
      to: "/clash",
    },
    {
      id: "issue",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.issue.in.real", label: "Real clashes" },
      ],
      outputs: [
        { labelKey: "cases.run_a_clash_profile_audit.step.issue.out.bcf", label: "BCF issues" },
      ],
      titleKey: "cases.run_a_clash_profile_audit.step.issue.title",
      titleDefault: "Push them out as issues",
      whatKey: "cases.run_a_clash_profile_audit.step.issue.what",
      whatDefault:
        "Turn each real clash into a BCF issue with its viewpoint and owner, so it is tracked to resolution and does not reappear on the next run.",
      whyKey: "cases.run_a_clash_profile_audit.step.issue.why",
      whyDefault:
        "A clash that is not assigned is a clash that stays. Pushing the real ones out as owned issues is the difference between an audit and a solved problem.",
      moduleLabel: "Model Issues",
      moduleLabelKey: "nav.model_issues",
      to: "/bcf",
    },
  ],
};

export default playbook;
