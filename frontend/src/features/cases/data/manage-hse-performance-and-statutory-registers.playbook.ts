// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage HSE performance and statutory registers".
//
// Keep the statutory registers, log and investigate incidents, track the
// leading and lagging safety indicators and act on the trend. Content strings
// are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-hse-performance-and-statutory-registers",
  order: 1021,
  category: "quality",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  icon: "ShieldCheck",
  titleKey: "cases.manage_hse_performance_and_statutory_registers.title",
  titleDefault: "Manage HSE performance and statutory registers",
  descKey: "cases.manage_hse_performance_and_statutory_registers.desc",
  descDefault:
    "Keep the statutory health and safety registers current, log and investigate incidents, track the leading and lagging indicators and act on the trend before a near miss becomes an injury.",
  longDescKey: "cases.manage_hse_performance_and_statutory_registers.longdesc",
  longDescDefault:
    "Safety is managed by what you measure and record. The statutory registers keep you legal; the incident log and the indicators tell you whether the site is actually getting safer. Watching the leading indicators is how you act before the lagging ones spike.",
  estMinutes: 11,
  steps: [
    {
      id: "registers",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.in.statutory", label: "Statutory duties" },
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.in.people", label: "People and plant" },
      ],
      outputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.out.registers", label: "Current registers" },
      ],
      titleKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.title",
      titleDefault: "Keep the registers current",
      whatKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.what",
      whatDefault:
        "Keep the statutory registers up to date: inductions, training and competencies, plant and lifting inspections, hazardous substances and the emergency arrangements.",
      whyKey: "cases.manage_hse_performance_and_statutory_registers.step.registers.why",
      whyDefault:
        "The registers are the first thing an inspector asks for and the first thing a defence rests on. Kept live rather than reconstructed, they show a site that is genuinely in control.",
      moduleLabel: "HSE Management",
      moduleLabelKey: "nav.hse_advanced",
      to: "/projects/:projectId/hse-advanced",
    },
    {
      id: "incident",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.incident.in.event", label: "Incident or near miss" },
      ],
      outputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.incident.out.investigation", label: "Investigation and actions" },
      ],
      titleKey: "cases.manage_hse_performance_and_statutory_registers.step.incident.title",
      titleDefault: "Log and investigate incidents",
      whatKey: "cases.manage_hse_performance_and_statutory_registers.step.incident.what",
      whatDefault:
        "Log every incident and near miss, investigate to the root cause rather than the obvious one, and record the corrective actions with owners and dates.",
      whyKey: "cases.manage_hse_performance_and_statutory_registers.step.incident.why",
      whyDefault:
        "The near miss you investigate today is the injury you prevent next month. An investigation that stops at blame instead of cause fixes nothing and lets the same event happen again.",
      moduleLabel: "HSE Management",
      moduleLabelKey: "nav.hse_advanced",
      to: "/projects/:projectId/hse-advanced",
    },
    {
      id: "indicators",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.indicators.in.data", label: "Registers and incidents" },
      ],
      outputs: [
        { labelKey: "cases.manage_hse_performance_and_statutory_registers.step.indicators.out.trend", label: "Safety trend" },
      ],
      titleKey: "cases.manage_hse_performance_and_statutory_registers.step.indicators.title",
      titleDefault: "Track the indicators",
      whatKey: "cases.manage_hse_performance_and_statutory_registers.step.indicators.what",
      whatDefault:
        "Track the leading indicators - inspections done, observations raised, close-out rate - alongside the lagging ones like incident and lost-time rates, and read the trend.",
      whyKey: "cases.manage_hse_performance_and_statutory_registers.step.indicators.why",
      whyDefault:
        "Lagging indicators tell you where you have already been hurt. Leading ones tell you where you are heading, so watching them is what lets you steer the site away from harm in time.",
      moduleLabel: "Safety",
      moduleLabelKey: "safety.title",
      to: "/projects/:projectId/safety",
    },
  ],
};

export default playbook;
