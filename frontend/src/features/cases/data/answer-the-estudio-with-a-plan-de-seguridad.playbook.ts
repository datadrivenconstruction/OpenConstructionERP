// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Answer the estudio de seguridad y salud with a plan" (ES).
//
// Under RD 1627/1997 the promotor commissions an estudio de seguridad y salud
// with the project, and the contractor answers it with a plan de seguridad y
// salud of their own before work starts. The plan is approved by the
// coordinador, not by the contractor who wrote it, and that approval is the
// gate. The case follows that shape: read what the estudio asks, work it into
// an analysis per activity, route it for approval, and then keep the site
// record that shows the plan is being followed rather than filed.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "answer-the-estudio-with-a-plan-de-seguridad",
  order: 1143,
  region: "ES",
  category: "site",
  stage: "plan",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["hse-officer", "site-manager", "project-manager"],
  icon: "ShieldCheck",
  titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.title",
  titleDefault: "Answer the estudio de seguridad y salud with a plan",
  descKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.desc",
  descDefault:
    "Read what the estudio actually requires, turn it into a risk analysis per activity you can hand a foreman, route the plan de seguridad y salud to the coordinador for approval before anyone starts, and keep the site record that shows it is being worked to.",
  longDescKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.longdesc",
  longDescDefault:
    "A plan de seguridad y salud is not a copy of the estudio with a different cover. It is the contractor's answer, in their own means and methods, to the risks the estudio identified, and it has to be approved by the coordinador de seguridad y salud before the works open. The two failures are opposite and equally common: a plan so generic that no activity on this site is recognisable in it, and a plan so long that nobody on site has read past the index. What follows keeps the plan as the approved document it has to be, and puts the working detail where a foreman meets it, as an analysis per activity, a permit where the risk needs one, and a recurring check that leaves a record.",
  estMinutes: 18,
  steps: [
    {
      id: "read",
      icon: "FileSearch",
      inputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.in.estudio",
          label: "Estudio de seguridad y salud document",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.in.project",
          label: "Project drawings and method",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.out.filed",
          label: "Filed safety document",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.out.requirements",
          label: "Requirements you must answer",
        },
      ],
      titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.title",
      titleDefault: "Read the estudio as a list of things to answer",
      whatKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.what",
      whatDefault:
        "File the estudio, or the estudio basico on a smaller job, with the project documents and pull out of it the risks, the protecciones colectivas and the singular works it names. That list, not the document, is what your plan has to answer point by point.",
      whyKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.read.why",
      whyDefault:
        "A coordinador reading your plan is checking whether every risk the estudio raised has an answer in it. Extracting the list first turns approval from a conversation about tone into a comparison anybody can run, and it is the fastest way to a plan approved on the first pass.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "analyse",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.in.requirements",
          label: "Requirements you must answer",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.in.activities",
          label: "Site activities and sequence",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.out.analysis",
          label: "Risk analysis per activity",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.out.controls",
          label: "Controls named with an owner",
        },
      ],
      titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.title",
      titleDefault: "Work it into an analysis per activity",
      whatKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.what",
      whatDefault:
        "Break the work into the activities you will actually run and analyse each one: the hazards, the collective protection first, the personal protection after it, and who is responsible. Mark the works that need a permit and the ones that need a recurso preventivo present.",
      whyKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.analyse.why",
      whyDefault:
        "This is the part of the plan a foreman uses. Written per activity it can be handed out at the start of a task and understood in two minutes; written as chapters of prose it is legally complete and operationally invisible, which is how a site ends up compliant on paper and unsafe on the ground.",
      moduleLabel: "HSE Management",
      moduleLabelKey: "nav.hse_advanced",
      to: "/projects/:projectId/hse-advanced",
    },
    {
      id: "approve",
      icon: "Stamp",
      inputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.in.plan",
          label: "Draft safety plan",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.in.coordinator",
          label: "Coordinador named for approval",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.out.approved",
          label: "Approved safety plan",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.out.trail",
          label: "Approval trail with dates",
        },
      ],
      titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.title",
      titleDefault: "Route the plan to the coordinador",
      whatKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.what",
      whatDefault:
        "Send the plan through an approval route that names the coordinador de seguridad y salud as the approver, or on a public work the Administration that approves it on the coordinador's informe, and keep the same route for every later revision, because a plan is amended whenever the method or the subcontractors change. The approved plan is what goes with the comunicacion de apertura del centro de trabajo to the autoridad laboral before the site opens.",
      whyKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.approve.why",
      whyDefault:
        "The approval, and its date, is what makes the plan the governing document. Revisions are where it quietly comes apart: the plan on site is version one, the method changed in March, and nobody can say whether the change was ever approved. A route that every version goes through answers that without anybody having to remember.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "checks",
      icon: "ListChecks",
      inputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.in.approved",
          label: "Approved safety plan",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.in.controls",
          label: "Controls named in the plan",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.out.forms",
          label: "Recurring site check forms",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.out.evidence",
          label: "Dated evidence of each check",
        },
      ],
      titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.title",
      titleDefault: "Turn the promises into checks somebody runs",
      whatKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.what",
      whatDefault:
        "Every recurring commitment in the plan, the weekly scaffold check, the daily edge protection walk, the check before a lift, becomes a form with a frequency and an owner rather than a sentence in a document.",
      whyKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.checks.why",
      whyDefault:
        "A commitment with no form behind it is a commitment that produces no evidence, and an inspection asking what you did about it gets an anecdote. The forms are also the cheapest way to find out that a control the plan relies on has quietly stopped happening.",
      moduleLabel: "Forms & checklists",
      moduleLabelKey: "nav.forms",
      to: "/forms",
    },
    {
      id: "record",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.in.site",
          label: "Site works under way",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.in.forms",
          label: "Completed check forms",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.out.log",
          label: "Observation and incident log",
        },
        {
          labelKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.out.actions",
          label: "Corrective actions tracked to close",
        },
      ],
      titleKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.title",
      titleDefault: "Keep the record the plan is judged by",
      whatKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.what",
      whatDefault:
        "Log the observations, the near misses and the incidents against the project as they happen, with a corrective action on each one and a date it was closed. This is the running record that sits alongside the libro de incidencias the coordinador keeps.",
      whyKey: "cases.answer_the_estudio_with_a_plan_de_seguridad.step.record.why",
      whyDefault:
        "An approved plan and an empty log describe a site where either nothing has gone wrong or nothing is being written down, and no inspector reads it the first way. The log is also the only thing that shows a repeat: the same observation three times is a control that does not work, not three careless people.",
      moduleLabel: "Safety",
      moduleLabelKey: "nav.safety",
      to: "/projects/:projectId/safety",
    },
  ],
};

export default playbook;
