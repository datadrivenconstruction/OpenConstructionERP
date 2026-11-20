// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Track an opportunity from enquiry to tender".
//
// Follow a lead end to end: capture the client contacts, run the opportunity
// through the CRM pipeline, convert the win into a live project and carry it
// into the tender you will price and submit.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "track-an-opportunity-from-enquiry-to-tender",
  order: 308,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["commercial-manager", "estimator"],
  icon: "TrendingUp",
  titleKey: "cases.track_an_opportunity_from_enquiry_to_tender.title",
  titleDefault: "Track an opportunity from enquiry to tender",
  descKey: "cases.track_an_opportunity_from_enquiry_to_tender.desc",
  descDefault:
    "Capture the client contacts, run the opportunity through the pipeline, convert the win into a project and carry it into tender.",
  estMinutes: 7,
  steps: [
    {
      id: "contact",
      icon: "Users",
      inputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.in.enquiry",
          label: "Incoming enquiry",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.in.details",
          label: "Client details",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.out.client",
          label: "Client record",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.out.contacts",
          label: "Contact records",
        },
      ],
      titleKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.title",
      titleDefault: "Record the client and contacts",
      whatKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.what",
      whatDefault:
        "Add the client and the key people behind the enquiry, with their roles and how to reach them.",
      whyKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.contact.why",
      whyDefault:
        "Enquiries arrive by phone and email and get lost. One clean contact record is who you chase and who signs.",
      moduleLabel: "Contacts",
      moduleLabelKey: "contacts.title",
      to: "/contacts",
    },
    {
      id: "opportunity",
      icon: "TrendingUp",
      inputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.in.client",
          label: "Client record",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.in.scope",
          label: "Enquiry scope",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.out.opportunity",
          label: "Opportunity record",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.out.stage",
          label: "Stage & probability",
        },
      ],
      titleKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.title",
      titleDefault: "Open and track the opportunity",
      whatKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.what",
      whatDefault:
        "Open the opportunity, set its value, stage and win probability, and log every call and meeting against it.",
      whyKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.opportunity.why",
      whyDefault:
        "A pipeline you cannot see is one you cannot forecast. Stage and probability tell you what to chase and what to staff for.",
      moduleLabel: "CRM",
      moduleLabelKey: "nav.crm",
      to: "/crm",
    },
    {
      id: "new-project",
      icon: "Building2",
      inputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.in.won",
          label: "Won opportunity",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.in.scope",
          label: "Client & scope",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.out.project",
          label: "Live project",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.out.carried",
          label: "Scope carried across",
        },
      ],
      titleKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.title",
      titleDefault: "Convert the win to a project",
      whatKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.what",
      whatDefault:
        "When the enquiry is won, spin it up as a live project and carry the client and scope across.",
      whyKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.new-project.why",
      whyDefault:
        "Re-keying a won job into a fresh system loses detail and wastes a day. Converting keeps the history and starts delivery clean.",
      moduleLabel: "New project",
      moduleLabelKey: "nav.projects_new",
      to: "/projects/new",
    },
    {
      id: "tender",
      icon: "Gavel",
      inputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.in.project",
          label: "Live project",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.in.scope",
          label: "Project scope",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.out.tender",
          label: "Tender package",
        },
        {
          labelKey:
            "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.out.bid",
          label: "Submitted bid",
        },
      ],
      titleKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.title",
      titleDefault: "Carry it into the tender",
      whatKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.what",
      whatDefault:
        "Move the won opportunity into tendering to build, price and submit the bid.",
      whyKey:
        "cases.track_an_opportunity_from_enquiry_to_tender.step.tender.why",
      whyDefault:
        "The commercial thread should run unbroken from first enquiry to submitted price. A gap is where scope and margin leak out.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
  ],
};

export default playbook;
