// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Choose the Building Code compliance path for B1 and E2" (NZ).
//
// The New Zealand Building Code is performance based: it says what a building
// has to achieve and not how. Compliance can be shown by following an
// Acceptable Solution or a Verification Method, which the consent authority
// must accept, or by an alternative solution, which it has to be satisfied
// about on reasonable grounds. This case is the design-side decision between
// those two, worked on the two clauses that decide most New Zealand houses:
// B1 Structure and E2 External moisture. It sits before the consent case
// rather than inside it. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "choose-the-building-code-compliance-path-for-b1-and-e2",
  order: 1470,
  region: "NZ",
  category: "quality",
  companyTypes: ["designer", "general-contractor", "developer-client", "bim-consultant"],
  roles: ["design-lead", "bim-coordinator", "project-manager", "document-controller"],
  icon: "ShieldCheck",
  titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.title",
  titleDefault: "Choose the Building Code compliance path for B1 and E2",
  descKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.desc",
  descDefault:
    "Test each element against the acceptable solution it would normally use, mark where the design steps outside it, assemble the evidence an alternative solution needs, pin the cladding system and its cavity to real product information, put the path to the consent authority and carry the durability periods into the defects record.",
  longDescKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.longdesc",
  longDescDefault:
    "The Building Code sets performance, not method, so there is always more than one legitimate way to comply and the choice has consequences long after the design is signed. Following an Acceptable Solution is the cheap path, because a building consent authority must accept it: for structure, B1/AS1 points at NZS 3604 for timber framed buildings within its scope, and a building outside that scope needs specific engineering design instead. For external moisture, E2/AS1 scores a building across wind zone, number of storeys, roof to wall intersection design, eaves width, envelope complexity and deck design, and the resulting risk score decides whether a cladding may be direct fixed or has to sit over a drained and vented cavity. Past the top of that range the building leaves the acceptable solution altogether. An alternative solution is entirely legal and sometimes the only honest answer, but it shifts the burden: the authority has to be satisfied on reasonable grounds, and reasonable grounds are something you assemble rather than assert.",
  estMinutes: 17,
  steps: [
    {
      id: "path",
      icon: "Split",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.in.design",
          label: "Design as it stands",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.in.clauses",
          label: "Code clauses that apply",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.out.inside",
          label: "Elements inside an acceptable solution",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.out.risk",
          label: "External moisture risk score",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.title",
      titleDefault: "Test each element against the solution it would normally use",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.what",
      whatDefault:
        "Run the design against the acceptable solutions clause by clause. For B1, is the building inside the scope of NZS 3604 for timber framing, on span, height, wall bracing and ground conditions, or does it need specific engineering design. For E2, score the building across wind zone, number of storeys, roof to wall intersection, eaves width, envelope complexity and decks, and read what the score requires of the cladding.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.path.why",
      whyDefault:
        "Both of these are scope questions answered by arithmetic rather than by judgement, and both are routinely answered by assumption. A building that is one storey and one wind zone outside the scope of the standard it was drawn to is not slightly non-compliant, it is on a different compliance path entirely, and finding that out at consent is finding it out after the fee proposal was written.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "departures",
      icon: "Crosshair",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.in.inside",
          label: "Elements inside an acceptable solution",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.in.model",
          label: "Coordinated model",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.out.marked",
          label: "Departures marked on the model",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.out.owner",
          label: "An owner for each one",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.title",
      titleDefault: "Mark every place the design leaves the acceptable solution",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.what",
      whatDefault:
        "Raise each departure as an issue against the location it occurs at: the cantilever the standard does not cover, the parapet detail with no acceptable solution behind it, the junction where two claddings meet. Give each one an owner and a decision, either bring it back inside the solution or take it forward as an alternative solution.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.departures.why",
      whyDefault:
        "Departures do not announce themselves on a drawing, and a design carrying six of them looks exactly like a design carrying none. Marked at a location they can be counted, priced and argued about while there is still time to change the design; discussed only in words they turn into a consent processing request halfway through the decision period.",
      moduleLabel: "Model Issues",
      moduleLabelKey: "nav.model_issues",
      to: "/bcf",
    },
    {
      id: "evidence",
      icon: "FileSearch",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.in.marked",
          label: "Departures marked on the model",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.in.sources",
          label: "Tests, calculations and history",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.out.pack",
          label: "Alternative solution evidence pack",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.out.thin",
          label: "Claims with nothing behind them",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.title",
      titleDefault: "Assemble the reasonable grounds, do not assert them",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.what",
      whatDefault:
        "For each alternative solution, build the file that supports it: the engineer's calculations, test results, in-service history of the same detail in the same exposure, comparison with the acceptable solution it departs from, and expert opinion where that is what the evidence is. Note where a claim currently rests on nothing but a supplier's brochure.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.evidence.why",
      whyDefault:
        "An alternative solution is not a weaker form of compliance, it is the same standard reached by a different route, and the difference is who carries the burden of showing it. The consent authority has to be satisfied on reasonable grounds, and a design team that has not written down what those grounds are is asking a processing officer to invent them under time pressure, which is how a good detail gets refused.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "product",
      icon: "PackageCheck",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.in.risk",
          label: "External moisture risk score",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.in.systems",
          label: "Proposed cladding systems",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.out.approved",
          label: "Systems accepted with their evidence",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.out.limits",
          label: "Limits of use recorded",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.title",
      titleDefault: "Tie the cladding system to its real limits of use",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.what",
      whatDefault:
        "Put each cladding, membrane and junction system through submittal with the evidence it relies on: a product certificate, an appraisal, or a manufacturer's technical literature. Record the limits of use that come with it, the wind zones it covers, whether it is approved direct fixed or over a cavity, the substrates and the details it has been assessed with, and check those against the risk score the design carries.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.product.why",
      whyDefault:
        "A certified system used outside its limits of use is an uncertified system, and the limits are where the certification actually lives. This is also the step where a substitution is caught: a cladding swapped on price after consent may be perfectly good and still be assessed for a lower wind zone than the building sits in, and nothing on the drawing will say so.",
      moduleLabel: "Submittals",
      moduleLabelKey: "submittals.title",
      to: "/projects/:projectId/submittals",
    },
    {
      id: "submit",
      icon: "Upload",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.in.pack",
          label: "Alternative solution evidence pack",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.in.approved",
          label: "Systems accepted with their evidence",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.out.stated",
          label: "Compliance path stated per clause",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.out.queries",
          label: "Queries answered against it",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.title",
      titleDefault: "Tell the authority which path each clause takes",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.what",
      whatDefault:
        "Submit with the compliance path written out clause by clause: which parts follow an acceptable solution or verification method and which are alternative solutions, and for each alternative what the evidence is and where it sits in the pack. Answer processing queries against that same table rather than against the drawings alone.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.submit.why",
      whyDefault:
        "A processing officer has to record how each clause is satisfied, and a submission that does not say makes them work it out from the drawings. That is slow, it is where requests for further information come from, and it produces the worst outcome of all, which is an alternative solution accepted without anybody noticing it was one, leaving nothing on the file when the building is sold ten years later.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "durability",
      icon: "CalendarCheck",
      inputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.in.stated",
          label: "Compliance path stated per clause",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.in.elements",
          label: "Elements and how replaceable they are",
        },
      ],
      outputs: [
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.out.periods",
          label: "Durability periods per element",
        },
        {
          labelKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.out.watch",
          label: "Details worth watching after handover",
        },
      ],
      titleKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.title",
      titleDefault: "Carry the durability periods past handover",
      whatKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.what",
      whatDefault:
        "Record the durability the Code requires of each element and hold it against the warranty record: 50 years for structure and anything else difficult to access or replace, 15 years for elements that are moderately difficult, and 5 years for those that are easy to access and replace. Flag the details that came through as alternative solutions so somebody looks at them first if water ever appears.",
      whyKey: "cases.choose_the_building_code_compliance_path_for_b1_and_e2.step.durability.why",
      whyDefault:
        "Weathertightness failures do not surface during a defects liability period, they surface years later, and by then the only thing anybody has is the file. A record that says which junctions were alternative solutions and what evidence they rested on turns a leak into a targeted investigation. Without it, the investigation is of the whole building.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
  ],
};

export default playbook;
