// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a 4D construction sequence".
//
// Link model elements to schedule activities, play the build order, check it
// works on the ground and use the 4D view to drive progress. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-4d-construction-sequence",
  order: 1011,
  category: "planning",
  companyTypes: ["general-contractor", "project-manager", "bim-consultant"],
  icon: "CalendarClock",
  titleKey: "cases.build_a_4d_construction_sequence.title",
  titleDefault: "Build a 4D construction sequence",
  descKey: "cases.build_a_4d_construction_sequence.desc",
  descDefault:
    "Link model elements to schedule activities, play the build order back as a 4D animation, check it actually works on the ground and use the same view to drive and report progress.",
  longDescKey: "cases.build_a_4d_construction_sequence.longdesc",
  longDescDefault:
    "A bar chart tells you when; a 4D sequence shows you how it builds. Watching the model assemble in programme order surfaces the access clash, the crane reach and the out-of-sequence pour that a Gantt chart hides until the crew hits it on site.",
  estMinutes: 12,
  steps: [
    {
      id: "model",
      icon: "Box",
      inputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.model.in.model", label: "Coordinated model" },
        { labelKey: "cases.build_a_4d_construction_sequence.step.model.in.programme", label: "Baseline programme" },
      ],
      outputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.model.out.ready", label: "Model ready to link" },
      ],
      titleKey: "cases.build_a_4d_construction_sequence.step.model.title",
      titleDefault: "Open the model",
      whatKey: "cases.build_a_4d_construction_sequence.step.model.what",
      whatDefault:
        "Open the coordinated model and confirm elements are grouped the way the job is built - by zone, level and pour - so they can be tied to activities cleanly.",
      whyKey: "cases.build_a_4d_construction_sequence.step.model.why",
      whyDefault:
        "A model organised by design discipline does not match how the site is sequenced. Grouping it the way the work happens is what makes a 4D link meaningful rather than cosmetic.",
      moduleLabel: "BIM Viewer",
      moduleLabelKey: "bim.title",
      to: "/projects/:projectId/bim",
    },
    {
      id: "link",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.link.in.ready", label: "Model elements" },
        { labelKey: "cases.build_a_4d_construction_sequence.step.link.in.activities", label: "Schedule activities" },
      ],
      outputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.link.out.linked", label: "Elements linked to time" },
      ],
      titleKey: "cases.build_a_4d_construction_sequence.step.link.title",
      titleDefault: "Link elements to activities",
      whatKey: "cases.build_a_4d_construction_sequence.step.link.what",
      whatDefault:
        "Map each element or group to the schedule activity that builds it, so every part of the model knows when it goes up and comes down.",
      whyKey: "cases.build_a_4d_construction_sequence.step.link.why",
      whyDefault:
        "The link is what turns a static model and a flat programme into a moving picture. It also flushes out the elements nobody scheduled and the activities with nothing to build.",
      moduleLabel: "Schedule",
      moduleLabelKey: "schedule.title",
      to: "/schedule",
    },
    {
      id: "sequence",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.sequence.in.linked", label: "Linked model" },
      ],
      outputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.sequence.out.reviewed", label: "Sequence reviewed" },
        { labelKey: "cases.build_a_4d_construction_sequence.step.sequence.out.clashes", label: "Time clashes found" },
      ],
      titleKey: "cases.build_a_4d_construction_sequence.step.sequence.title",
      titleDefault: "Play and review the sequence",
      whatKey: "cases.build_a_4d_construction_sequence.step.sequence.what",
      whatDefault:
        "Play the sequence and watch the build order: check access stays open, cranes can reach, temporary works come and go in time, and nothing is built before what holds it up.",
      whyKey: "cases.build_a_4d_construction_sequence.step.sequence.why",
      whyDefault:
        "Finding an out-of-sequence pour or a blocked access on screen costs an hour. Finding it on site costs a week and a standing crew. The 4D review is where that saving is made.",
      moduleLabel: "Schedule",
      moduleLabelKey: "schedule.title",
      to: "/schedule",
    },
    {
      id: "track",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.track.in.reviewed", label: "Agreed sequence" },
      ],
      outputs: [
        { labelKey: "cases.build_a_4d_construction_sequence.step.track.out.progress", label: "Visual progress" },
      ],
      titleKey: "cases.build_a_4d_construction_sequence.step.track.title",
      titleDefault: "Track progress against it",
      whatKey: "cases.build_a_4d_construction_sequence.step.track.what",
      whatDefault:
        "Use the 4D view to mark what is built and compare it to the planned sequence, so progress is shown as coloured geometry the whole team can read at a glance.",
      whyKey: "cases.build_a_4d_construction_sequence.step.track.why",
      whyDefault:
        "A planned-versus-built model tells a client more in one image than a page of percentages. It makes slippage impossible to hide and easy to talk about honestly.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
  ],
};

export default playbook;
