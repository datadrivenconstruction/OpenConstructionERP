// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Take a building from permit to final acceptance" (SA).
//
// The Saudi end game has two tracks that must not be confused. The municipal
// track runs from the building permit, applied for electronically by a
// licensed engineering office on the owner's behalf, through the completion
// certificate to the occupancy certificate. The contractual track, on a
// government works contract, runs from preliminary handover through the
// maintenance period to final handover, and it is final handover that
// releases the final guarantee. A building can hold its occupancy certificate
// and still be a year away from final acceptance. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "take-a-building-from-permit-to-final-acceptance",
  order: 1197,
  region: "SA",
  category: "handover",
  companyTypes: ["general-contractor", "developer-client", "project-manager", "owner-operator"],
  roles: ["project-manager", "contract-administrator", "document-controller"],
  stage: "handover",
  icon: "KeyRound",
  titleKey: "cases.take_a_building_from_permit_to_final_acceptance.title",
  titleDefault: "Take a building from permit to final acceptance",
  descKey: "cases.take_a_building_from_permit_to_final_acceptance.desc",
  descDefault:
    "Get the permit and record its conditions, build to what was permitted, clear the list before preliminary handover, take the completion and occupancy certificates, work the maintenance period, and reach final acceptance with the guarantee released rather than forgotten.",
  longDescKey: "cases.take_a_building_from_permit_to_final_acceptance.longdesc",
  longDescDefault:
    "Two sequences run at the end of a Saudi project and each has its own paper. The municipality issues the building permit against a design a licensed engineering office certified, inspects at completion, issues the certificate of construction completion, and only then the occupancy certificate that allows the building to be used. The contract runs its own course: preliminary handover, which is where the works are taken over and the maintenance period starts, then the maintenance period itself, then final handover, which is what releases the final guarantee and the last of the money. Teams that treat the occupancy certificate as the end of the job leave a guarantee outstanding and a defects obligation running that nobody is watching, and both are still live liabilities twelve months later.",
  estMinutes: 17,
  steps: [
    {
      id: "permit",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.in.design", label: "Certified design" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.in.title", label: "Land and title documents" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.out.permit", label: "Building permit issued" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.out.conditions", label: "Permit conditions recorded" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.title",
      titleDefault: "Get the permit and write down what it conditions",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.what",
      whatDefault:
        "Track the permit application through the municipal platform, lodged by the licensed engineering office the owner has authorised, and record what comes back: the permit, its validity, and every condition attached to it, from setbacks and heights to the inspections that must happen before certain work is covered.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.permit.why",
      whyDefault:
        "A permit is an approval with conditions, and the conditions are the part that gets filed and forgotten. They surface again at the completion inspection, months after the work they governed was covered up, and the cost of proving a condition was met after the fact is nothing like the cost of meeting it in front of a witness.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "build",
      icon: "HardHat",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.in.permit", label: "Permit and permitted drawings" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.in.changes", label: "Changes proposed on site" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.out.controlled", label: "Deviations controlled" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.out.record", label: "As permitted record kept" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.title",
      titleDefault: "Build what was permitted, and control what changes",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.what",
      whatDefault:
        "Keep the permitted drawings as the reference the site works to, and route any change that touches what the permit approved back through the engineering office before it is built, not after. Record the ones that need a permit amendment separately from the ones that do not.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.build.why",
      whyDefault:
        "The completion inspection compares the building against the permitted drawings, so a deviation is discovered by the inspector rather than declared by the builder. An unapproved change of use, an extra floor area or a moved boundary can stop the completion certificate outright, and the building is finished, occupied by nobody and earning nothing while it is resolved.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "construction_control.title",
      to: "/projects/:projectId/construction-control",
    },
    {
      id: "punch",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.in.walk", label: "Pre-handover walk" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.in.trades", label: "Trades still on site" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.out.closed", label: "Items closed and verified" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.out.remaining", label: "Remaining items agreed" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.title",
      titleDefault: "Clear the list before you ask for handover",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.what",
      whatDefault:
        "Walk the building with the consultant, log each item with its location and a photograph, drive the list down while the trades are still mobilised, and agree in writing which few items will be carried into the handover record as outstanding.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.punch.why",
      whyDefault:
        "Everything left open at handover is done later at several times the cost, because the scaffolding is down, the crews are on another job and the building is occupied. An agreed short list is also the only version of the handover conversation where the consultant has no reason to refuse, since the disagreement is about a named handful rather than about whether the building is finished.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "preliminary",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.in.cleared", label: "Cleared punch list" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.in.contract", label: "Contract handover terms" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.out.minute", label: "Preliminary handover recorded" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.out.start", label: "Maintenance period start date" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.title",
      titleDefault: "Hold the preliminary handover and date the maintenance period",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.what",
      whatDefault:
        "Run the handover against the contract terms and record what a handover record has to say: the date, who attended, what was taken over, what was reserved and the date the maintenance period starts and ends, in the calendar the contract expresses it in.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.preliminary.why",
      whyDefault:
        "Preliminary handover is the hinge on a Saudi works contract. It is when the employer takes the works over, when the maintenance obligation begins to run, and, on a government contract, the event the final payment claim waits for under the Government Tenders and Procurement Law. A handover with no recorded date leaves every one of those questions open, and each of them is worth money to somebody.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "certificates",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.in.asbuilt", label: "As built drawings" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.in.inspection", label: "Final inspection" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.out.completion", label: "Completion certificate" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.out.occupancy", label: "Occupancy certificate" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.title",
      titleDefault: "Take the completion certificate, then the occupancy certificate",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.what",
      whatDefault:
        "Submit for the certificate of construction completion with the engineering office reports and the as built drawings, pass the final inspection against the permitted design, and then apply for the occupancy certificate, which is a separate application resting on the inspections and connections that make the building fit to be used.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.certificates.why",
      whyDefault:
        "These are two documents and people plan for one. The completion certificate says the building was built as permitted. The occupancy certificate is what allows it to be occupied, and a tenant handover date set from the completion certificate is a date that will be missed. Sequencing them explicitly is what turns a six week surprise into a six week plan.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "maintenance",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.in.reserved", label: "Reserved items" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.in.reported", label: "Defects reported in use" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.out.register", label: "Defects register" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.out.owner", label: "Each defect owned by a party" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.title",
      titleDefault: "Work the maintenance period rather than wait it out",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.what",
      whatDefault:
        "Register the reserved items and everything reported once the building is in use against the party obliged to put it right, with the warranty that covers it and the date the obligation ends, and record each rectification with the evidence that it was done.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.maintenance.why",
      whyDefault:
        "The maintenance period is the last window in which somebody else pays to fix the building, and it closes on a date. A defect reported to a facilities team and written into nobody's register is one the owner quietly ends up funding, and a subcontractor whose own liability is not tracked against the main obligation walks away from work you will still be answerable for.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "final",
      icon: "Trophy",
      inputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.in.register", label: "Closed defects register" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.in.guarantee", label: "Final guarantee outstanding" },
      ],
      outputs: [
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.out.acceptance", label: "Final handover recorded" },
        { labelKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.out.released", label: "Guarantee and balance released" },
      ],
      titleKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.title",
      titleDefault: "Reach final acceptance and get the guarantee back",
      whatKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.what",
      whatDefault:
        "At the end of the maintenance period, close the register, ask for final handover on the contract's terms, and follow the two things that turn on it: the release of the final guarantee back to the bank and the payment of the balance the employer has been holding.",
      whyKey: "cases.take_a_building_from_permit_to_final_acceptance.step.final.why",
      whyDefault:
        "A final guarantee nobody asks to release stays on the bank's books, consuming the facility that would have supported the next tender. It is the least dramatic money on the project and the easiest to leave behind, because by then the site team has gone and the only person who would notice is the one reading the facility utilisation a year later.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
