// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Evidence Saudi Building Code compliance" (SA).
//
// The Saudi Building Code is a set of volumes, not one book: SBC 201 for the
// general requirements, the 300 series for structure, SBC 401 for electrical
// work, SBC 601 for energy and SBC 801 for fire protection, issued by the
// Saudi Building Code National Committee. Compliance is evidenced twice, once
// in the design the licensed engineering office submits for review, and again
// in the products actually installed, which for imported goods means the
// conformity documents issued through the national platform. This case builds
// that evidence as the job runs instead of assembling it at handover.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "evidence-saudi-building-code-compliance",
  order: 1194,
  region: "SA",
  category: "quality",
  companyTypes: ["designer", "general-contractor", "project-manager", "developer-client"],
  roles: ["design-lead", "project-manager", "document-controller"],
  stage: "design",
  icon: "ShieldCheck",
  titleKey: "cases.evidence_saudi_building_code_compliance.title",
  titleDefault: "Evidence Saudi Building Code compliance",
  descKey: "cases.evidence_saudi_building_code_compliance.desc",
  descDefault:
    "Name the code volumes the job is built to, take the design through review, approve materials before they are ordered, check the conformity documents on imported products, test against the clause rather than against the specification, and leave a compliance file somebody else can read.",
  longDescKey: "cases.evidence_saudi_building_code_compliance.longdesc",
  longDescDefault:
    "Building work in the Kingdom is governed by the Saudi Building Code, and a permit is issued against a design a licensed engineering office has certified as complying with it. The volumes divide by discipline: SBC 201 carries the general building requirements, the 300 series covers structure from loads and forces through soils, concrete, masonry and steel, SBC 401 covers electrical work, SBC 601 energy and SBC 801 fire protection. What trips projects is not the design, which is reviewed by people who know the code. It is the gap that opens afterwards, when a product is substituted on price, arrives without the conformity documents an imported product needs, and is installed into work that has already been approved on a different specification. This case closes that gap by making the approval of a material a step with a document behind it rather than a conversation on site.",
  estMinutes: 17,
  steps: [
    {
      id: "volumes",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.volumes.in.brief", label: "Design brief and occupancy" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.volumes.in.contract", label: "Contract specification" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.volumes.out.register", label: "Code register for the job" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.volumes.out.owners", label: "A discipline owner per volume" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.volumes.title",
      titleDefault: "Name the code volumes this building is built to",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.volumes.what",
      whatDefault:
        "Record the volumes that govern the job and the edition of each: SBC 201 for the general requirements, the 300 series for the structure, SBC 401 for electrical, SBC 601 for energy and SBC 801 for fire protection, together with whichever others the occupancy pulls in. Give each one a named discipline owner.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.volumes.why",
      whyDefault:
        "A specification that says the works shall comply with the Saudi Building Code has said almost nothing, because the code is a shelf of volumes with editions. Naming volume and edition is what lets a reviewer check a clause and a contractor price to a standard rather than to a phrase, and it is the difference between an argument about the clause and an argument about which book you were both reading.",
      moduleLabel: "Quality Management",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "review",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.review.in.drawings", label: "Design drawings and calculations" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.review.in.register", label: "Code register" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.review.out.comments", label: "Review comments closed" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.review.out.certified", label: "Design certified for submission" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.review.title",
      titleDefault: "Take the design through review before it goes to the authority",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.review.what",
      whatDefault:
        "Route the drawings and calculations through the reviewing parties in order, the licensed engineering office that will certify the submission last, and record every comment against the clause it cites and the revision that answered it.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.review.why",
      whyDefault:
        "The permit is issued on a design an engineering office has put its name to, so the office's comments are not opinions, they are the conditions of the certificate. Answering them in a marked up PDF that nobody keeps means the same comment returns three revisions later, and the reviewer, who does keep a record, reads the repetition as a design that is not being controlled.",
      moduleLabel: "Review Authority",
      moduleLabelKey: "review_authority.title",
      to: "/projects/:projectId/review-authority",
    },
    {
      id: "submittals",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.submittals.in.spec", label: "Specification clause" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.submittals.in.proposal", label: "Proposed product" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.submittals.out.approved", label: "Material approved" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.submittals.out.rejected", label: "Substitutions refused" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.submittals.title",
      titleDefault: "Approve the material before anybody orders it",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.submittals.what",
      whatDefault:
        "Raise a submittal for each material and system, with the clause it answers, the test evidence or type approval behind it and the standard it is certified to, and get it approved or refused with a date. Where a substitution is proposed on price or on lead time, run it through the same route rather than around it.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.submittals.why",
      whyDefault:
        "The expensive failure is never the product that was refused, it is the one nobody submitted. Material that arrives on site with no approval behind it is material somebody will have to justify after it is built in, and the cost of taking it out is paid by whoever cannot show the paper. A dated approval is also the record that decides who pays when the code compliance of an installed system is questioned.",
      moduleLabel: "Submittals",
      moduleLabelKey: "submittals.title",
      to: "/projects/:projectId/submittals",
    },
    {
      id: "conformity",
      icon: "Container",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.conformity.in.orders", label: "Purchase orders" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.conformity.in.imports", label: "Imported consignments" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.conformity.out.certificates", label: "Conformity certificates held" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.conformity.out.clearance", label: "Consignments clear customs" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.conformity.title",
      titleDefault: "Check the conformity documents on anything imported",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.conformity.what",
      whatDefault:
        "For every imported product covered by a Saudi technical regulation, confirm the supplier holds a product certificate of conformity and that each consignment is accompanied by a shipment certificate, both issued electronically through the national conformity platform, and file them against the purchase order rather than in the freight forwarder's email.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.conformity.why",
      whyDefault:
        "Conformity certification is a customs gate, not a quality nicety. A consignment of cable or of fire rated doors that arrives without its shipment certificate sits at the port while the certificate is chased, and the delay lands on the critical path of whichever trade was waiting. Checking it at the order stage costs an email and moves the risk to the supplier who can actually fix it.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "inspect",
      icon: "FlaskConical",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.inspect.in.approved", label: "Approved materials" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.inspect.in.plan", label: "Inspection and test plan" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.inspect.out.results", label: "Test results against the clause" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.inspect.out.signed", label: "Signed inspection records" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.inspect.title",
      titleDefault: "Test against the clause, not against the delivery note",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.inspect.what",
      whatDefault:
        "Work the inspection and test plan on site with the code clause named on each hold point: concrete sampled and tested at the frequency the structural volumes require, earthworks compaction proven, fire stopping inspected before it is concealed, and every result signed by whoever witnessed it.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.inspect.why",
      whyDefault:
        "A test result without the clause it answers is a number in a folder. Named against the clause, the same result closes a hold point and can be handed to a reviewer without a covering explanation. The hold points that matter most are the ones that get covered up, because the only alternative evidence is opening the work again.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "ncr",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.ncr.in.failures", label: "Failed tests and findings" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.ncr.in.clause", label: "Clause not met" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.ncr.out.ncr", label: "Non-conformance raised" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.ncr.out.disposition", label: "Disposition agreed" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.ncr.title",
      titleDefault: "Raise a non-conformance when a clause is not met",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.ncr.what",
      whatDefault:
        "Where work does not meet the clause, raise it as a non-conformance naming the volume and the clause, the extent of the work affected and the proposed disposition, whether that is rework, repair, a concession sought from the designer or acceptance as is, and close it with the evidence that the disposition was carried out.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.ncr.why",
      whyDefault:
        "Non-conformances handled informally are handled twice, once quietly on site and once loudly at handover when the reviewer asks about the same pour. Recorded, the item has an extent, an owner and an end, and a concession granted by the designer is a decision with a name on it rather than a rumour that the engineer said it was fine.",
      moduleLabel: "NCRs",
      moduleLabelKey: "ncr.title",
      to: "/projects/:projectId/ncr",
    },
    {
      id: "file",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.file.in.records", label: "Approvals, tests, closures" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.file.in.drawings", label: "As built drawings" },
      ],
      outputs: [
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.file.out.file", label: "Compliance file" },
        { labelKey: "cases.evidence_saudi_building_code_compliance.step.file.out.index", label: "Indexed by clause" },
      ],
      titleKey: "cases.evidence_saudi_building_code_compliance.step.file.title",
      titleDefault: "Leave a compliance file somebody else can read",
      whatKey: "cases.evidence_saudi_building_code_compliance.step.file.what",
      whatDefault:
        "Assemble the file the building will be judged on: approved submittals with their conformity certificates, test and inspection records, closed non-conformances and the as built drawings, indexed by the code volume and clause each item answers.",
      whyKey: "cases.evidence_saudi_building_code_compliance.step.file.why",
      whyDefault:
        "The file is read by people who were not there, at completion, at the sale of the asset, and after an incident. Indexed by clause it answers a question in a minute. Filed by trade and date it answers nothing, and the practical effect is that work which was compliant gets treated as unproven, which costs the same as being wrong.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
