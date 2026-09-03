// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Register the project under RERA and file the quarterly report" (IN).
//
// The Real Estate (Regulation and Development) Act 2016 turns a private
// residential or commercial development into a reporting obligation. Above the
// threshold the state authority sets, the project has to be registered before
// anything is marketed, booked or sold; areas have to be quoted as carpet area
// rather than as any built-up figure; and a progress report goes to the
// authority's portal every quarter for the life of the registration, carrying
// physical progress, financial progress and the status of approvals.
//
// The Act is central and the administration is not. Registration thresholds,
// fees, the portal and the exact form of the quarterly return differ between
// state authorities, so the state authority is the reference for anything the
// project is actually held to. Public works departments are outside it
// entirely; this is a developer's obligation, not a contractor's.
//
// What makes it a case rather than a form-filling exercise is the completion
// date. It is declared at registration, it is public, and delay past it carries
// interest to every buyer on everything they have paid. So the quarterly report
// is not paperwork about the past, it is the early warning about that date.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "register-the-project-under-rera-and-file-the-quarterly-report",
  order: 1187,
  region: "IN",
  category: "commercial",
  companyTypes: ["developer-client", "project-manager", "cost-consultant", "owner-operator"],
  roles: ["project-manager", "document-controller", "commercial-manager", "quantity-surveyor"],
  icon: "Building2",
  titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.title",
  titleDefault: "Register the project under RERA and file the quarterly report",
  descKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.desc",
  descDefault:
    "Decide whether the scheme needs registration, register it with the completion date you can defend, quote carpet area everywhere, then keep physical and financial progress in a shape the quarterly return can be produced from without a scramble.",
  longDescKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.longdesc",
  longDescDefault:
    "Two obligations under the Act cost developers real money for reasons that have nothing to do with construction. The first is the area basis: agreements and marketing have to quote carpet area, the net usable floor area within the walls, and a scheme whose internal figures are kept on any other basis will publish one number and sell against another until somebody notices. The second is the declared completion date, which is stated at registration, is visible to every buyer, and carries interest on everything received if it slips. Both are fed by the same discipline, which is that the project's own measurement and progress records are kept in the units the Act uses rather than translated at reporting time. This case sets that up at registration and then runs the quarterly cycle off it, so the return is produced from the records instead of assembled beside them.",
  estMinutes: 22,
  steps: [
    {
      id: "scope",
      icon: "Building2",
      inputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.in.scheme",
          label: "The scheme and its phasing",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.in.threshold",
          label: "The state authority's threshold",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.out.applies",
          label: "Whether registration is required",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.out.phases",
          label: "What is registered as one project",
        },
      ],
      titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.title",
      titleDefault: "Settle what counts as the project before you register it",
      whatKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.what",
      whatDefault:
        "Set the scheme up with its land area, unit count and phasing, and check it against the registration threshold the state authority applies. Decide which phases are registered separately and which are one project, and record why.",
      whyKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.scope.why",
      whyDefault:
        "Phasing decides the completion dates you will be held to, and it is easier to argue before registration than after. A phase registered inside a larger project inherits that project's date even when its own work is shorter, and nothing later undoes that.",
      moduleLabel: "Property Development",
      moduleLabelKey: "nav.property_dev",
      to: "/property-dev",
    },
    {
      id: "register",
      icon: "Stamp",
      inputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.in.approvals",
          label: "Sanctioned plans and approvals",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.in.programme",
          label: "The programme behind the date",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.out.registration",
          label: "Registration on file with its number",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.out.date",
          label: "The declared completion date",
        },
      ],
      titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.title",
      titleDefault: "Register with a completion date the programme supports",
      whatKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.what",
      whatDefault:
        "Lodge the registration with the state authority and keep the submission, the approvals it relied on and the certificate itself against the project. Record the declared completion date where the programme can be read against it.",
      whyKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.register.why",
      whyDefault:
        "The declared date is the most expensive sentence in the application, because delay past it is compensated to buyers on everything they have paid. A date taken from the sales plan rather than from the programme is a liability accepted at the moment of registration, in writing, in public.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "area",
      icon: "Ruler",
      inputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.in.drawings",
          label: "Unit drawings",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.out.carpet",
          label: "Carpet area per unit",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.out.one",
          label: "One area basis everywhere",
        },
      ],
      titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.title",
      titleDefault: "Measure carpet area and use it everywhere",
      whatKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.what",
      whatDefault:
        "Measure each unit to the definition the Act uses, the net usable floor area within the walls, and make that figure the one the agreement, the marketing material and the internal cost per unit all run on.",
      whyKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.area.why",
      whyDefault:
        "Two area bases in one organisation is not a documentation problem, it is a pricing problem. Cost per unit computed on one basis and price per unit quoted on the other is wrong by whatever the loading factor is, quietly, on every unit in the scheme.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "progress",
      icon: "Gauge",
      inputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.in.site",
          label: "Work done on site",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.in.spend",
          label: "Money spent and received",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.out.physical",
          label: "Physical progress by element",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.out.financial",
          label: "Financial progress against it",
        },
      ],
      titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.title",
      titleDefault: "Keep physical and financial progress on the same spine",
      whatKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.what",
      whatDefault:
        "Record progress element by element, foundation, structure, external walls, internal finishes, services, external development, and keep the money committed and spent against those same elements rather than against a separate cost code.",
      whyKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.progress.why",
      whyDefault:
        "The quarterly return asks for physical and financial progress side by side, and the two are read against each other by anyone looking for trouble. Recording them on one structure makes that comparison an output; recording them separately makes it a quarterly reconciliation exercise, done in a hurry, under a deadline.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "file",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.in.quarter",
          label: "The quarter's progress and approvals",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.out.return",
          label: "The quarterly return, produced not assembled",
        },
        {
          labelKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.out.warning",
          label: "Early warning on the declared date",
        },
      ],
      titleKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.title",
      titleDefault: "Produce the quarterly return, and read it as a warning",
      whatKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.what",
      whatDefault:
        "Generate the quarter's report from the progress records, with the status of each approval and the photographs for the period, file it with the authority, and compare the trend against the declared completion date.",
      whyKey: "cases.register_the_project_under_rera_and_file_the_quarterly_report.step.file.why",
      whyDefault:
        "Four returns show a trend the fourth quarter cannot hide. A developer who reads them as an early warning has a year to act on a slipping date; one who treats them as filing finds out at handover, when the only remaining options cost money to buyers.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
