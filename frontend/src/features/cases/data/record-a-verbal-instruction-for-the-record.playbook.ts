// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Record a verbal instruction for the record".
//
// Site runs on verbal instructions, but a verbal costs you nothing you can
// prove. Log the call, confirm it in writing, and if it moved the scope start
// the change record before you build it.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "record-a-verbal-instruction-for-the-record",
  order: 340,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["site-manager", "contract-administrator", "commercial-manager"],
  icon: "ClipboardList",
  titleKey: "cases.record_a_verbal_instruction_for_the_record.title",
  titleDefault: "Record a verbal instruction for the record",
  descKey: "cases.record_a_verbal_instruction_for_the_record.desc",
  descDefault:
    "A verbal instruction costs you nothing you can prove. Log the call while it is fresh, confirm it back in writing, and if it moved the scope start the change record before you build it.",
  estMinutes: 7,
  steps: [
    {
      id: "log",
      icon: "MessageSquare",
      inputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.log.in.call",
          label: "Verbal instruction",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.log.in.caller",
          label: "Caller & time",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.log.out.entry",
          label: "Dated call log",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.log.out.record",
          label: "Instruction on record",
        },
      ],
      titleKey:
        "cases.record_a_verbal_instruction_for_the_record.step.log.title",
      titleDefault: "Log the call",
      whatKey: "cases.record_a_verbal_instruction_for_the_record.step.log.what",
      whatDefault:
        "Straight after the call, log it, who rang, when, and exactly what was said or instructed, in their words rather than your paraphrase. Do it while you still remember the detail.",
      whyKey: "cases.record_a_verbal_instruction_for_the_record.step.log.why",
      whyDefault:
        "A fortnight on, nobody agrees what was said on the phone. A dated log written the same hour is the difference between a fact and your word against theirs.",
      moduleLabel: "Phone Log",
      moduleLabelKey: "nav.phone_log",
      to: "/projects/:projectId/phone-log",
    },
    {
      id: "confirm",
      icon: "Send",
      inputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.confirm.in.log",
          label: "Dated call log",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.confirm.in.understanding",
          label: "Understood instruction",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.confirm.out.note",
          label: "Confirmation note",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.confirm.out.filed",
          label: "Filed correspondence",
        },
      ],
      titleKey:
        "cases.record_a_verbal_instruction_for_the_record.step.confirm.title",
      titleDefault: "Confirm it in writing",
      whatKey:
        "cases.record_a_verbal_instruction_for_the_record.step.confirm.what",
      whatDefault:
        "Send a short confirmation-of-verbal-instruction note back to whoever gave it, setting out what you understood and that you are acting on it unless told otherwise. File it against the project.",
      whyKey:
        "cases.record_a_verbal_instruction_for_the_record.step.confirm.why",
      whyDefault:
        "A verbal instruction only binds once it is put in writing and left unchallenged. The confirmation note turns a corridor conversation into an instruction you can rely on and, later, be paid for.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "record",
      icon: "FileSignature",
      inputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.record.in.note",
          label: "Confirmation note",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.record.in.scope",
          label: "Scope change",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.record.out.order",
          label: "Change order",
        },
        {
          labelKey:
            "cases.record_a_verbal_instruction_for_the_record.step.record.out.entitlement",
          label: "Entitlement logged",
        },
      ],
      titleKey:
        "cases.record_a_verbal_instruction_for_the_record.step.record.title",
      titleDefault: "Start the change record if scope moved",
      whatKey:
        "cases.record_a_verbal_instruction_for_the_record.step.record.what",
      whatDefault:
        "If the instruction added to or changed the scope, raise the change order now, before the work is done, so the extra is captured against an agreed reason and the clock starts on your entitlement.",
      whyKey:
        "cases.record_a_verbal_instruction_for_the_record.step.record.why",
      whyDefault:
        "Work done first and papered afterwards is the work that never gets paid. Starting the change record before you act is what keeps a verbal instruction from turning into free scope.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
  ],
};

export default playbook;
