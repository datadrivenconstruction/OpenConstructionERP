// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Import a programme and set the baseline".
//
// Bring an external programme in from an exchange file, check calendars and
// links survived, set the accepted programme as the baseline and publish it so
// progress is measured against it. Content strings key plus inline default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "import-a-programme-and-set-the-baseline",
  order: 1010,
  category: "planning",
  companyTypes: ["general-contractor", "project-manager", "subcontractor"],
  icon: "FileInput",
  titleKey: "cases.import_a_programme_and_set_the_baseline.title",
  titleDefault: "Import a programme and set the baseline",
  descKey: "cases.import_a_programme_and_set_the_baseline.desc",
  descDefault:
    "Bring an external programme in from an exchange file, check the calendars and links survived the trip, set the accepted programme as the baseline and publish it so progress is measured against something fixed.",
  longDescKey: "cases.import_a_programme_and_set_the_baseline.longdesc",
  longDescDefault:
    "A programme built in another planning tool is worth reusing, not retyping. The value is in importing it cleanly, agreeing it as the baseline, and then never moving that baseline again - because a baseline that keeps shifting can never tell you that the job is late.",
  estMinutes: 10,
  steps: [
    {
      id: "import",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.import.in.file", label: "Programme exchange file" },
      ],
      outputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.import.out.activities", label: "Imported activities" },
      ],
      titleKey: "cases.import_a_programme_and_set_the_baseline.step.import.title",
      titleDefault: "Import the programme",
      whatKey: "cases.import_a_programme_and_set_the_baseline.step.import.what",
      whatDefault:
        "Import the programme from its exchange file so the activities, durations, logic links and WBS come across without being rekeyed line by line.",
      whyKey: "cases.import_a_programme_and_set_the_baseline.step.import.why",
      whyDefault:
        "Retyping a programme of a few hundred activities loses the logic that makes it a programme. Importing keeps the network intact so the critical path is real, not redrawn from memory.",
      moduleLabel: "Advanced Schedule",
      moduleLabelKey: "nav.schedule_advanced",
      to: "/schedule-advanced",
    },
    {
      id: "check",
      icon: "Waypoints",
      inputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.check.in.activities", label: "Imported activities" },
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.check.in.calendars", label: "Calendars and links" },
      ],
      outputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.check.out.clean", label: "Checked programme" },
      ],
      titleKey: "cases.import_a_programme_and_set_the_baseline.step.check.title",
      titleDefault: "Check what came across",
      whatKey: "cases.import_a_programme_and_set_the_baseline.step.check.what",
      whatDefault:
        "Confirm the calendars, the logic links and the WBS survived the import, and that the completion date matches the source, before anyone trusts a date on it.",
      whyKey: "cases.import_a_programme_and_set_the_baseline.step.check.why",
      whyDefault:
        "Exchange files drop constraints and remap calendars silently. Catching a shifted completion date now is far cheaper than discovering the imported programme was wrong three months in.",
      moduleLabel: "Advanced Schedule",
      moduleLabelKey: "nav.schedule_advanced",
      to: "/schedule-advanced",
    },
    {
      id: "baseline",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.baseline.in.clean", label: "Checked programme" },
      ],
      outputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.baseline.out.baseline", label: "Fixed baseline" },
      ],
      titleKey: "cases.import_a_programme_and_set_the_baseline.step.baseline.title",
      titleDefault: "Set the baseline",
      whatKey: "cases.import_a_programme_and_set_the_baseline.step.baseline.what",
      whatDefault:
        "Freeze the agreed programme as the baseline, the fixed reference the job will be measured against for the rest of its life.",
      whyKey: "cases.import_a_programme_and_set_the_baseline.step.baseline.why",
      whyDefault:
        "The baseline is the promise. Without a frozen one there is nothing to compare progress to, and every slippage argument becomes a matter of opinion instead of a matter of record.",
      moduleLabel: "Schedule",
      moduleLabelKey: "schedule.title",
      to: "/schedule",
    },
    {
      id: "publish",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.publish.in.baseline", label: "Fixed baseline" },
      ],
      outputs: [
        { labelKey: "cases.import_a_programme_and_set_the_baseline.step.publish.out.tracking", label: "Progress tracking on" },
      ],
      titleKey: "cases.import_a_programme_and_set_the_baseline.step.publish.title",
      titleDefault: "Publish it for tracking",
      whatKey: "cases.import_a_programme_and_set_the_baseline.step.publish.what",
      whatDefault:
        "Publish the baseline so the team records progress against it and the planned-versus-actual picture builds from day one.",
      whyKey: "cases.import_a_programme_and_set_the_baseline.step.publish.why",
      whyDefault:
        "A baseline nobody tracks against is a wall decoration. Publishing it turns the programme into a live control that warns you early rather than a document reviewed after the fact.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
  ],
};

export default playbook;
