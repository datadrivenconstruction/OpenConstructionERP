// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run overlapping PCBU duties on a shared site" (NZ).
//
// The Health and Safety at Work Act 2015 rebuilt New Zealand health and safety
// law around the person conducting a business or undertaking, and the part that
// changes daily practice on a construction site is that duties are not
// transferable and more than one PCBU can owe the same duty at the same time.
// A head contractor cannot hand its duty to a subcontractor by writing it into
// a subcontract; it can only discharge it by consulting, cooperating and
// coordinating. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-overlapping-pcbu-duties-on-a-shared-site",
  order: 1460,
  region: "NZ",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager", "owner-operator"],
  roles: ["hse-officer", "site-manager", "foreman", "project-manager"],
  icon: "HardHat",
  titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.title",
  titleDefault: "Run overlapping PCBU duties on a shared site",
  descKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.desc",
  descDefault:
    "Identify the risks and what is reasonably practicable about them, list every other business working on the site, agree in writing who does what where the duties overlap, engage the workers who do the work, keep the daily record, notify what has to be notified and give the officers something they can exercise due diligence with.",
  longDescKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.longdesc",
  longDescDefault:
    "Under the Health and Safety at Work Act 2015 the duty holder is the PCBU, the person conducting a business or undertaking, and its primary duty is to ensure the health and safety of workers and of anyone else the work puts at risk, so far as is reasonably practicable. On a construction site there are always several PCBUs at once: the head contractor, every subcontractor, the crane hire company, sometimes the client. The Act says their duties overlap rather than transfer, and that each of them must consult, cooperate with and coordinate activities with the others so far as they share a duty about the same matter. That single sentence is what a site safety system has to be built around, because it means the question is never whose fault an unsafe scaffold is. It is what each business that knew about it did about it, and whether any of them can show it.",
  estMinutes: 15,
  steps: [
    {
      id: "risks",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.in.work",
          label: "Work planned for the site",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.in.conditions",
          label: "Site and its surroundings",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.out.register",
          label: "Risks named and ranked",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.out.controls",
          label: "Controls and why they are enough",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.title",
      titleDefault: "Name the risks and what is reasonably practicable about them",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.what",
      whatDefault:
        "Work through the risks the job actually creates, eliminate what can be eliminated and minimise the rest, and write down the reasoning: how likely the harm is, how serious it would be, what is known about the risk and about ways of controlling it, and what those controls cost relative to that. Keep the reasoning with the control rather than only the control.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.risks.why",
      whyDefault:
        "Reasonably practicable is a defined test in this Act, not a general appeal to common sense, and it is applied afterwards by someone reading a file. A control with no reasoning behind it is indistinguishable from a control that was chosen because it was cheap, and the difference between those two is the whole of a defence.",
      moduleLabel: "Safety",
      moduleLabelKey: "nav.safety",
      to: "/projects/:projectId/safety",
    },
    {
      id: "who",
      icon: "Users",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.in.subcontracts",
          label: "Subcontracts and hire agreements",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.in.presence",
          label: "Who is on site this month",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.out.list",
          label: "Every PCBU on the site listed",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.out.contact",
          label: "A named person for each one",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.title",
      titleDefault: "List every business the site has a duty alongside",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.what",
      whatDefault:
        "Keep a live list of every business working on or into the site, not only the direct subcontractors: labour hire, plant hire with an operator, scaffolders, testing and surveying, the client's own trades. Record a named person for each, with the work they are here to do and the period they are here for.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.who.why",
      whyDefault:
        "You cannot consult, cooperate and coordinate with a business you have not written down, and the ones that get left off a list are exactly the ones that arrive for two days, do something high risk and leave. Plant hire with an operator is the classic: the operator is another PCBU's worker, working under your site rules, on your programme.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "overlap",
      icon: "Handshake",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.in.list",
          label: "Every PCBU on the site listed",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.in.shared",
          label: "Risks more than one of them touches",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.out.agreement",
          label: "Who does what, in writing",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.out.gaps",
          label: "Risks nobody had taken",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.title",
      titleDefault: "Agree who does what where the duties overlap",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.what",
      whatDefault:
        "Take the risks that more than one business touches, scaffold and edge protection, traffic and pedestrian movements, services, lifting over other trades, and agree in writing who provides the control, who inspects it, who may alter it and how a change is told to everyone else. Review the agreement when the trades on site change, not only at the start.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.overlap.why",
      whyDefault:
        "The Act requires each PCBU to consult, cooperate with and coordinate activities with the others so far as their duties overlap, and it does not let any of them contract out of the duty itself. What an agreement can do is stop two businesses each assuming the other inspected the scaffold, which is the exact shape of most serious harm on a multi-trade site.",
      moduleLabel: "HSE Management",
      moduleLabelKey: "nav.hse_advanced",
      to: "/projects/:projectId/hse-advanced",
    },
    {
      id: "workers",
      icon: "UserCheck",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.in.agreement",
          label: "Who does what, in writing",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.in.crews",
          label: "Crews arriving on site",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.out.inducted",
          label: "Inductions and briefings recorded",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.out.voice",
          label: "A route for workers to raise things",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.title",
      titleDefault: "Engage the people who actually do the work",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.what",
      whatDefault:
        "Induct every crew onto the site controls and the agreement behind them, brief changes when they happen rather than at the next monthly meeting, and give workers a real route to raise a hazard, through health and safety representatives where the site has them. Record who was briefed on what and when.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.workers.why",
      whyDefault:
        "Worker engagement and participation is a duty in its own right under this Act and not a courtesy, and it is also the cheapest source of information a site has. The person who knows the excavation is moving is the person standing in it, and whether that reaches the site office is a question about the route, not about the person.",
      moduleLabel: "Site Supervision",
      moduleLabelKey: "site_supervision.title",
      to: "/projects/:projectId/site-supervision",
    },
    {
      id: "record",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.in.day",
          label: "What happened on the day",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.in.attendance",
          label: "Who was on site",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.out.diary",
          label: "Daily record kept as it happens",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.out.actions",
          label: "Actions raised and closed",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.title",
      titleDefault: "Keep the daily record the same way every day",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.what",
      whatDefault:
        "Record each day as it runs: who was on site, what work went on, the weather where it mattered, the safety observations made and what was done about them, and any change to a shared control. Close out the actions rather than only raising them.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.record.why",
      whyDefault:
        "A diary kept every day is evidence and a diary written up in the week after an incident is a liability, and the two are easy to tell apart. It is also the record that answers the only question an investigation really asks, which is what the business knew and when it knew it.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "notify",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.in.event",
          label: "Event or hazardous work planned",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.in.thresholds",
          label: "What has to be notified",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.out.sent",
          label: "Notification sent and logged",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.out.scene",
          label: "Scene preserved where required",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.title",
      titleDefault: "Notify what the Act says must be notified",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.what",
      whatDefault:
        "Keep two notification routines running from the same set of forms. Particular hazardous construction work, such as deep excavation, work at height above the prescribed limit and certain lifting, has to be notified to the regulator at least 24 hours before it starts. A notifiable event, a death, a notifiable injury or illness or a notifiable incident, has to be notified as soon as possible after it happens, and the site left undisturbed except to help someone or make it safe.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.notify.why",
      whyDefault:
        "These are the two duties most often discovered after the fact, and both carry offences of their own regardless of whether anyone was hurt. Disturbing a scene is the one that does lasting damage: it destroys the evidence that would have shown what the controls actually were, and the business that cleared the site is the business that cannot now prove anything about it.",
      moduleLabel: "Forms & checklists",
      moduleLabelKey: "nav.forms",
      to: "/forms",
    },
    {
      id: "officers",
      icon: "Gauge",
      inputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.in.records",
          label: "Site records across projects",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.in.events",
          label: "Events, actions and notifications",
        },
      ],
      outputs: [
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.out.pack",
          label: "What the officers are shown",
        },
        {
          labelKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.out.trend",
          label: "Where the same risk keeps returning",
        },
      ],
      titleKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.title",
      titleDefault: "Give the officers something they can act on",
      whatKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.what",
      whatDefault:
        "Report to the people who govern the business, not only to the ones who run the site: what the risks across the portfolio are, what resources have been put against them, what events happened and what was done, and where the same hazard keeps coming back on different jobs. Show the actions that are still open as well as the ones closed.",
      whyKey: "cases.run_overlapping_pcbu_duties_on_a_shared_site.step.officers.why",
      whyDefault:
        "An officer of a PCBU owes a personal duty to exercise due diligence, which means keeping up to date, understanding the operations and their hazards, and making sure the business has and uses appropriate resources and processes. That duty cannot be discharged from a summary that only carries good news, and a board that was never shown the open actions is a board that cannot say it knew.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
