// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Steer a client-side project area by area".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "steer-a-client-project-area-by-area",
  order: 1680,
  category: "planning",
  stage: "define",
  companyTypes: ["developer-client", "project-manager", "owner-operator"],
  roles: ["project-manager", "commercial-manager", "design-lead"],
  requiresProject: true,
  icon: "Milestone",
  titleKey: "cases.steer_a_client_project_area_by_area.title",
  titleDefault: "Steer a client-side project area by area",
  descKey: "cases.steer_a_client_project_area_by_area.desc",
  descDefault:
    "Start here if you run a project for the client: set up the phase gates, then walk once through every management area, from stakeholders and delivery model to staffing, quality and money, and take the first gate decision with all of it on the table.",
  longDescKey: "cases.steer_a_client_project_area_by_area.longdesc",
  longDescDefault:
    "A client-side project manager answers for far more than cost and time. Someone has to decide how the project is delivered, who may commit money, which permits are needed, which long-lead plant must be ordered, who is on the team and what quality has to be proven. The platform gives each of these areas its own screen, and every area hands a binding document to the phase gate. This case visits each screen once, in the order a real project needs them, so you see the whole frame before you go deep into any one area. The German demo projects of the owner's project control pack fill every screen with a believable project.",
  estMinutes: 35,
  steps: [
    {
      id: "gates",
      icon: "Milestone",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.gates.in.charter", label: "Project brief and mandate" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.gates.out.gates", label: "Phase model with gates" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.gates.out.owners", label: "Area owners and deputies" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.gates.title",
      titleDefault: "Set up the phases and gates",
      whatKey: "cases.steer_a_client_project_area_by_area.step.gates.what",
      whatDefault:
        "Open Project governance, choose a phase model on the Phase model tab and pick the approval route that will decide at each gate. Then name an owner and a deputy for every management area in the matrix.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.gates.why",
      whyDefault:
        "Gates only work when it is clear who decides and who answers for each area. An area without an owner blocks its gate, so naming them first is what makes every later screen count.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance?tab=model",
    },
    {
      id: "stakeholders",
      icon: "Users",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.in.contacts", label: "Contacts and organisations" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.out.register", label: "Stakeholder register" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.out.plan", label: "Communication plan" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.title",
      titleDefault: "Register the stakeholders",
      whatKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.what",
      whatDefault:
        "Open Stakeholders, add the people and organisations who can influence the project, assess their interest and influence, and plan how and when each one is engaged.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.stakeholders.why",
      whyDefault:
        "Neighbours, authorities and funders who are forgotten at the start come back later as objections and delays. A register with an engagement plan turns them into dates you control.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=register",
    },
    {
      id: "delivery",
      icon: "Network",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.delivery.in.forms", label: "Delivery form catalogue" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.delivery.out.decision", label: "Proposed delivery decision" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.delivery.out.packages", label: "Package plan" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.delivery.title",
      titleDefault: "Choose the delivery model",
      whatKey: "cases.steer_a_client_project_area_by_area.step.delivery.what",
      whatDefault:
        "Open Delivery model, compare at least two forms of delivery against weighted criteria, confirm the risk allocation and split the work into contract packages.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.delivery.why",
      whyDefault:
        "Who designs, who builds and who carries which risk decides almost every later contract. Writing the comparison down makes the decision explainable at the gate and later in a dispute.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=comparison",
    },
    {
      id: "procurement",
      icon: "PackageCheck",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.procurement.in.packages", label: "Package plan" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.procurement.out.concept", label: "Procurement concept" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.procurement.out.schedule", label: "Award schedule" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.procurement.title",
      titleDefault: "Plan how each package is bought",
      whatKey: "cases.steer_a_client_project_area_by_area.step.procurement.what",
      whatDefault:
        "Open Procurement concept, plan the award route for every package, prepare the short lists and let the award schedule run back from the programme.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.procurement.why",
      whyDefault:
        "A package that is tendered too late holds up the site, and one tendered under the wrong procedure can be challenged. The concept fixes both before the first invitation goes out.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept",
    },
    {
      id: "design",
      icon: "PenTool",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.design.in.brief", label: "Design brief" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.design.out.schedule", label: "Design schedule" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.design.out.rules", label: "Numbering and release rules" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.design.title",
      titleDefault: "Organise the design work",
      whatKey: "cases.steer_a_client_project_area_by_area.step.design.what",
      whatDefault:
        "Open Design management, set the drawing numbering scheme, the design team and the design schedule, and decide who releases drawings for issue.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.design.why",
      whyDefault:
        "Design that is not planned arrives late and unchecked on site. A numbering scheme and a release rule agreed at the start keep every drawing traceable.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design",
    },
    {
      id: "permits",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.permits.in.route", label: "Project route and programme" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.permits.out.roadmap", label: "Permit roadmap" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.permits.title",
      titleDefault: "Map the permits the project needs",
      whatKey: "cases.steer_a_client_project_area_by_area.step.permits.what",
      whatDefault:
        "Open Permits, start the roadmap and add every permit the project needs with the date by which the decision has to be in hand.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.permits.why",
      whyDefault:
        "Permits are the classic critical path nobody owns. A roadmap with need-by dates shows months ahead which application must leave the office this week.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits",
    },
    {
      id: "plant",
      icon: "Container",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.plant.in.needs", label: "Equipment needs" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.plant.out.longlead", label: "Long-lead register" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.plant.title",
      titleDefault: "Register the long-lead plant",
      whatKey: "cases.steer_a_client_project_area_by_area.step.plant.what",
      whatDefault:
        "Open Plant register, add the equipment that has to be ordered early, record lead times with their source and see the last safe order date.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.plant.why",
      whyDefault:
        "Transformers, switchgear and lifts can take a year to arrive. Ordering them on time is a client decision that has to be made long before the builder is on site.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register",
    },
    {
      id: "logistics",
      icon: "Truck",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.logistics.in.siteplan", label: "Site plan and stages" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.logistics.out.logplan", label: "Logistics plan" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.logistics.out.readiness", label: "Gate readiness" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.logistics.title",
      titleDefault: "Plan the site logistics",
      whatKey: "cases.steer_a_client_project_area_by_area.step.logistics.what",
      whatDefault:
        "Open Site Logistics on the Logistics plan tab, set the stages and areas, check utilities against demand and confirm the plan is ready for the start gate.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.logistics.why",
      whyDefault:
        "A site that runs out of space, power or access stops every trade at once. Planning the logistics before the start is far cheaper than fixing it with the cranes standing.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=plan",
    },
    {
      id: "staffing",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.staffing.in.team", label: "Project team" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.staffing.out.staffplan", label: "Staffing plan" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.staffing.title",
      titleDefault: "Staff the project team",
      whatKey: "cases.steer_a_client_project_area_by_area.step.staffing.what",
      whatDefault:
        "Open Staffing, create the staffing plan from the role catalogue, assign people to the positions and check that every person holds the documents the role requires.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.staffing.why",
      whyDefault:
        "A key role left open or a person whose qualification has expired stops work as surely as a missing permit. The plan makes both visible before they bite.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing",
    },
    {
      id: "quality",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.quality.in.standards", label: "Standards and requirements" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.quality.out.qconcept", label: "Quality concept" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.quality.title",
      titleDefault: "Write the quality concept",
      whatKey: "cases.steer_a_client_project_area_by_area.step.quality.what",
      whatDefault:
        "Open Quality concept, record the standards and requirements, the proofs each package has to deliver and the stages of commissioning and acceptance.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.quality.why",
      whyDefault:
        "Quality that is not defined up front cannot be demanded later. The concept tells every contractor in advance what they will have to prove.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept",
    },
    {
      id: "money",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.money.in.authority", label: "Delegation of authority" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.money.out.releases", label: "Release rules and items" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.money.title",
      titleDefault: "Set who may commit money",
      whatKey: "cases.steer_a_client_project_area_by_area.step.money.what",
      whatDefault:
        "Open Commitments and releases, choose how strictly releases are enforced, name the approver for each authority tier and add the first commitment items.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.money.why",
      whyDefault:
        "Contracts signed without a release are the most common way a budget escapes. Tiered authority keeps every commitment inside a decision someone actually took.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments?tab=setup",
    },
    {
      id: "decide",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.decide.in.evidence", label: "Area plans and evidence" },
      ],
      outputs: [
        { labelKey: "cases.steer_a_client_project_area_by_area.step.decide.out.decision", label: "Recorded gate decision" },
        { labelKey: "cases.steer_a_client_project_area_by_area.step.decide.out.conditions", label: "Open conditions" },
      ],
      titleKey: "cases.steer_a_client_project_area_by_area.step.decide.title",
      titleDefault: "Take the gate decision",
      whatKey: "cases.steer_a_client_project_area_by_area.step.decide.what",
      whatDefault:
        "Back in Project governance, open the gate and press Start preparation, let each area owner confirm readiness, submit the gate for review and record the decision: go, go with conditions, hold, recycle or stop.",
      whyKey: "cases.steer_a_client_project_area_by_area.step.decide.why",
      whyDefault:
        "The gate is where the separate area plans become binding together. A recorded decision with its conditions is what the project steers by in the next phase.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance",
    },
  ],
};

export default playbook;
