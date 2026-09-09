// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Take a building consent through to code compliance" (NZ).
//
// The Building Act 2004 path from "does this even need a consent" to the code
// compliance certificate. The two twenty working day decision periods are the
// spine of it, and both of them are conditional: the first stops while a
// request for further information is outstanding, and the second only starts
// once the authority has everything it needs to be satisfied on reasonable
// grounds. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "take-a-building-consent-through-to-code-compliance",
  order: 1440,
  region: "NZ",
  category: "quality",
  companyTypes: ["general-contractor", "developer-client", "designer", "project-manager"],
  roles: ["project-manager", "site-manager", "document-controller", "design-lead"],
  icon: "Stamp",
  titleKey: "cases.take_a_building_consent_through_to_code_compliance.title",
  titleDefault: "Take a building consent through to code compliance",
  descKey: "cases.take_a_building_consent_through_to_code_compliance.desc",
  descDefault:
    "Settle whether the work needs a consent and whether any of it is restricted building work, lodge the application, answer the request for further information without losing the decision period, pass the inspections the consent names, collect the records of work and apply for the code compliance certificate.",
  longDescKey: "cases.take_a_building_consent_through_to_code_compliance.longdesc",
  longDescDefault:
    "Under the Building Act 2004 all building work has to comply with the Building Code whether or not it needs a consent, and most of it needs one unless it falls inside the exempt work in Schedule 1. The building consent authority has 20 working days to grant or refuse an application, but that period is suspended while a request for further information sits unanswered, which is why a consent that took four months on paper often took eighteen working days of the authority's time and the rest of it waiting for the applicant. The same shape repeats at the end: 20 working days to decide a code compliance certificate, and the same dependence on whether the file is complete. Restricted building work adds a third thread, because the primary structure and the external moisture management systems have to be designed and built or supervised by licensed practitioners who each owe a document. The whole case is really one discipline, which is keeping the file complete as the work happens rather than assembling it when the certificate is applied for.",
  estMinutes: 18,
  steps: [
    {
      id: "classify",
      icon: "SignpostBig",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.in.scope",
          label: "Scope of the building work",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.in.exempt",
          label: "Exempt work in Schedule 1",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.out.route",
          label: "Consent needed or not",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.out.rbw",
          label: "Restricted building work identified",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.title",
      titleDefault: "Settle the route before anybody draws anything",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.what",
      whatDefault:
        "Classify the work: does it need a building consent, does any part of it fall inside the exempt work Schedule 1 describes, and is any of it restricted building work, which is the design and construction of the primary structure and the external moisture management systems of a house or small to medium apartment building. Record the answer and what it rests on.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.classify.why",
      whyDefault:
        "Exempt work still has to comply with the Building Code, so exemption removes the paperwork and not the standard, and work exempted wrongly is unconsented building work that the territorial authority can require to be fixed years later. Restricted building work found at the end means finding a licensed practitioner willing to certify somebody else's finished work, which is the most expensive discovery in this whole case.",
      moduleLabel: "Route Classifier",
      moduleLabelKey: "project_route.title",
      to: "/projects/:projectId/project-route",
    },
    {
      id: "lodge",
      icon: "Upload",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.in.documents",
          label: "Drawings, specification and calculations",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.in.memo",
          label: "Designer's memorandum where required",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.out.lodged",
          label: "Application lodged and dated",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.out.clock",
          label: "Decision period running",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.title",
      titleDefault: "Lodge a complete application, not an early one",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.what",
      whatDefault:
        "Lodge the application with the building consent authority as one pack: the drawings and specification at the level of detail the Code compliance path needs, the structural and other calculations, the product information, and the memorandum from the licensed design practitioner where the work is restricted building work. Record the lodgement date, because the decision period runs from it.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.lodge.why",
      whyDefault:
        "The authority has 20 working days to grant or refuse, and an incomplete application does not shorten that period, it just spends it on a request for further information. Lodging two weeks early with half the structural documentation reliably costs more calendar time than lodging two weeks later with all of it.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "rfi",
      icon: "MessageSquare",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.in.request",
          label: "Request for further information",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.in.answer",
          label: "Design team's answer",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.out.response",
          label: "Response sent and logged",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.out.resumed",
          label: "Decision period resumed",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.title",
      titleDefault: "Answer the request before the file goes cold",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.what",
      whatDefault:
        "Log every request for further information against the application with the date it arrived, route each question to the person who can answer it, and send one consolidated response rather than a trickle. Keep the sent copy and the date, and record which drawings were superseded by the answer.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.rfi.why",
      whyDefault:
        "The decision period is suspended while a request is outstanding, so every day the answer sits with the design team is a day added to the consent and not a day of the authority's twenty. That is also why a request answered piecemeal is the slowest of all: the clock restarts and stops again with each round.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "inspect",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.in.consent",
          label: "Granted consent and its conditions",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.in.programme",
          label: "Construction programme",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.out.passed",
          label: "Inspections passed and dated",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.out.fixes",
          label: "Items to fix before the next one",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.title",
      titleDefault: "Book the inspections the consent names, in order",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.what",
      whatDefault:
        "Put the inspections the consent lists onto the programme as the activities they actually are, book each one before the work it covers is closed up, and record the result with the date and the inspector's findings. Where an inspection fails, record what has to be fixed and re-book it rather than carrying on.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.inspect.why",
      whyDefault:
        "The building consent authority can only issue a code compliance certificate if it is satisfied on reasonable grounds that the work complies, and the inspection record is most of those grounds. Work closed up before its inspection is work that may have to be opened again, and the cost of that is carried by whoever built it, not by whoever forgot to book.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "records",
      icon: "FileCheck",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.in.work",
          label: "Restricted building work carried out",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.in.producer",
          label: "Producer statements and test results",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.out.record",
          label: "Records of work collected",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.out.gaps",
          label: "Missing certificates named",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.title",
      titleDefault: "Collect the records while the trades are still on site",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.what",
      whatDefault:
        "Collect the record of work from every licensed building practitioner who carried out or supervised restricted building work, together with the producer statements, test results and product certificates the consent conditions call for. Track them as a list with the gaps named, not as a folder somebody will audit later.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.records.why",
      whyDefault:
        "A licensed practitioner owes a record of work on completion of their restricted building work, and chasing one from a subcontractor who left the job eight months ago is a different task from asking for it in the week they finished. Every missing document becomes a hold on the code compliance certificate, and the certificate is usually holding up settlement.",
      moduleLabel: "Quality Management",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "ccc",
      icon: "BadgeCheck",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.in.records",
          label: "Records of work collected",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.in.passed",
          label: "Inspections passed and dated",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.out.applied",
          label: "Certificate applied for",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.out.ccc",
          label: "Code compliance certificate issued",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.title",
      titleDefault: "Apply for the code compliance certificate",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.what",
      whatDefault:
        "Apply once the file is complete and the work is finished, with the inspection record, the records of work, the producer statements and the as-built information. The authority has 20 working days to decide, and it decides against the consent as granted, so any change made on site has to have been consented as an amendment before this point.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.ccc.why",
      whyDefault:
        "The certificate is what says the work complies with the consent, and its absence follows the building rather than the builder. A house without one is harder to sell, harder to insure and harder to finance, and the owner who inherits that problem is usually the one paying to solve it years after everyone who could have solved it cheaply has moved on.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "file",
      icon: "FileStack",
      inputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.in.ccc",
          label: "Code compliance certificate issued",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.in.systems",
          label: "Specified systems in the building",
        },
      ],
      outputs: [
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.out.pack",
          label: "Consent pack filed for the owner",
        },
        {
          labelKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.out.schedule",
          label: "Compliance schedule obligations noted",
        },
      ],
      titleKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.title",
      titleDefault: "Hand the owner the file the property will need",
      whatKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.what",
      whatDefault:
        "File the whole consent history where the owner and the next owner can find it: the consented drawings, the amendments, the inspection record, the certificates and the code compliance certificate itself. Where the building has specified systems, record the compliance schedule and the annual building warrant of fitness that now runs against it.",
      whyKey: "cases.take_a_building_consent_through_to_code_compliance.step.file.why",
      whyDefault:
        "The consent file is read by people who were not there: a purchaser's solicitor, an insurer, the designer of the next alteration. A complete file answers their questions without anybody being called; an incomplete one turns every future project on the building into an archaeology exercise, and the council's own property file is rarely as complete as the builder's was.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
