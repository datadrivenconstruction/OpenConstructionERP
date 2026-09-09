// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Close the object and take the vvod v ekspluatatsiyu" (RU).
//
// The permit to commission is not paperwork at the end, it is the last page of
// a record that had to be kept from the first day: the works journal, the acts
// signed as the work closed, and the as-built set assembled in the composition
// the rules list. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "close-the-object-and-take-the-vvod-v-ekspluatatsiyu",
  order: 1309,
  category: "handover",
  companyTypes: ["general-contractor", "developer-client", "project-manager", "cost-consultant"],
  roles: ["project-manager", "document-controller", "site-manager", "contract-administrator"],
  region: "RU",
  icon: "KeyRound",
  titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.title",
  titleDefault: "Close the object and take the vvod v ekspluatatsiyu",
  descKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.desc",
  descDefault:
    "Keep the obshchiy zhurnal rabot from the first day, file the acts and the material documents as they are signed, assemble the ispolnitelnaya dokumentatsiya in the composition RD-11-02-2006 lists, sign the acceptance, pass the final check of the state construction supervision and apply for the permit to commission under article 55 of the Town Planning Code.",
  longDescKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.longdesc",
  longDescDefault:
    "Commissioning a completed object in Russia is a documentary procedure, and almost all of it is decided long before anyone applies for anything. The state construction supervision body issues its conclusion of conformity after a final check that reads the works journal and the as-built set against the design documentation, and the permit to commission is then granted on a list of documents the code names. What sinks a handover is never the application. It is a journal begun three months late, an act of concealed work signed by somebody who was not entitled to sign it, or a set assembled from memory after the subcontractor who did the work has been paid and gone.",
  estMinutes: 15,
  steps: [
    {
      id: "journal",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.in.permit", label: "Construction permit" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.in.parties", label: "Parties and their authorities" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.out.journal", label: "Works journal open" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.out.signatories", label: "Signatories on record" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.title",
      titleDefault: "Open the works journal on the day the permit is issued",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.what",
      whatDefault:
        "Start the obshchiy zhurnal rabot in the form the supervision rules prescribe, register it where the rules require, and record from the outset who may sign on behalf of the developer, the contractor, the designer's supervision and the construction control service, with the orders that appointed them. Keep the specialised journals for the works that need their own.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.journal.why",
      whyDefault:
        "The journal is the primary record the supervision body reads at the final check, and it is read for continuity as much as for content, so a gap in it is a gap in the evidence that the work was controlled at all. An entry signed by a person whose appointment is not on file is worth no more than an unsigned one, and that is discovered at the end, when nobody can go back and be appointed retroactively.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "construction_control.title",
      to: "/projects/:projectId/construction-control",
    },
    {
      id: "acts",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.in.hidden", label: "Concealed work acts" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.in.materials", label: "Material passports and protocols" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.out.filed", label: "Acts filed by structure" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.out.missing", label: "Missing documents named" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.title",
      titleDefault: "File the acts and the material documents as they are signed",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.what",
      whatDefault:
        "As each piece of work closes, file its act of concealed works or of intermediate acceptance of a responsible structure together with what backs it: the passports and certificates for the materials built in, the laboratory protocols, the geodetic survey schemes and the drawings marked with what was actually built. Keep a running list of what is still missing, by structure rather than by supplier.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acts.why",
      whyDefault:
        "These documents are cheap to obtain in the week the work happens and close to impossible a year later, when the concrete supplier has changed its testing laboratory and the subcontractor has been paid in full. A list kept by structure also tells you which act is blocking the set, which a list kept by supplier never does.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "set",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.in.filed", label: "Acts filed by structure" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.in.composition", label: "Required composition list" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.out.set", label: "As-built set assembled" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.out.report", label: "Completeness report" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.title",
      titleDefault: "Assemble the as-built set and check it against the list",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.what",
      whatDefault:
        "Assemble the ispolnitelnaya dokumentatsiya in the composition RD-11-02-2006 sets out, in the order the register lists it, and run the completeness check yourself before handing it to anybody: every act present, every act referencing documents that exist, every sheet signed by a person entitled to sign it, and the volumes numbered so a reader can find a structure without asking you.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.set.why",
      whyDefault:
        "The supervision body checks the set against the same published list, so running that check first costs a day and moves every finding from their report into your worklist. A set handed over incomplete does not simply come back, it starts a round of correspondence that puts weeks between the last brick and the permit, and those weeks are usually financed.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "acceptance",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.in.set", label: "As-built set assembled" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.in.contract", label: "Contract scope" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.out.act", label: "Acceptance act signed" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.out.remarks", label: "Remarks list with dates" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.title",
      titleDefault: "Sign the acceptance of the finished object",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.what",
      whatDefault:
        "Hand the object over to the customer on the acceptance act the contract names, with the outstanding items listed as remarks, each with an owner and a date, rather than as a sentence saying the works are complete. Reconcile the accepted scope against everything already accepted month by month so the total agrees with the sum of the acts.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.acceptance.why",
      whyDefault:
        "The acceptance date starts the guarantee period and usually the release of the retained amounts, so it is a commercial event and not a ceremony. Remarks recorded without an owner and a date are the ones that reappear at the end of the guarantee period as defects, by which time the argument is about who caused them rather than about who agreed to fix them.",
      moduleLabel: "Handover & Closeout",
      moduleLabelKey: "closeout.title",
      to: "/closeout",
    },
    {
      id: "nadzor",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.in.set", label: "As-built set assembled" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.in.prior", label: "Prior inspection findings" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.out.zos", label: "Conclusion of conformity" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.out.cleared", label: "Findings cleared" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.title",
      titleDefault: "Pass the final check of the state construction supervision",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.what",
      whatDefault:
        "Close out every finding from the checks carried out during construction first, then call the final check, present the journal and the as-built set against the design documentation, and take the conclusion of conformity. Where the object is subject to environmental supervision, treat that conclusion as its own thread with its own dates.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.nadzor.why",
      whyDefault:
        "The conclusion of conformity is the document without which the permit to commission cannot be applied for at all, and it is refused on unclosed findings from checks that happened a year earlier. Treating each interim finding as closed only when the supervision body says it is closed, rather than when the work was redone, is what keeps that list empty at the end.",
      moduleLabel: "Inspections",
      moduleLabelKey: "inspections.title",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "permit",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.in.zos", label: "Conclusion of conformity" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.in.plan", label: "Technical plan" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.out.permit", label: "Permit to commission" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.out.cadastre", label: "Object on the cadastre" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.title",
      titleDefault: "Apply for the permit to commission",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.what",
      whatDefault:
        "Lodge the application with the body that issued the construction permit, attaching the documents article 55 of the Town Planning Code lists: the title and planning documents, the acceptance act, the conclusion of conformity, the documents on the utility connections, and the technical plan prepared by a cadastral engineer. Check the address and the technical parameters against the design before you send it.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.permit.why",
      whyDefault:
        "The grounds for refusing this permit are listed in the code and are almost all documentary, which means almost all of them are avoidable by reading the same list first. A parameter that disagrees with the design, an area that disagrees with the technical plan, is a refusal, and the object cannot be used or registered until it is resolved.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "guarantee",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.in.act", label: "Acceptance act signed" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.in.terms", label: "Guarantee terms" },
      ],
      outputs: [
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.out.register", label: "Guarantee register" },
        { labelKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.out.end", label: "End date under watch" },
      ],
      titleKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.title",
      titleDefault: "Start the guarantee period from the right date",
      whatKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.what",
      whatDefault:
        "Register the guarantee period from the acceptance date, with the equipment warranties that run on their own shorter clocks recorded separately, and put the end date in front of the person who will still be responsible for the building when it arrives. Keep the as-built set where that person can reach it rather than in the contractor's archive.",
      whyKey: "cases.close_the_object_and_take_the_vvod_v_ekspluatatsiyu.step.guarantee.why",
      whyDefault:
        "The contract guarantee and the longer statutory period for claims about the quality of a building are two different clocks, and the shorter one is the one everybody remembers. Registering both from the acceptance date is what makes a defect found in year four a question about the guarantee rather than a question about whether anybody kept the paperwork.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
  ],
};

export default playbook;
