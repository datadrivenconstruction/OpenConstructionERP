// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Close the works and hand over the libro del edificio" (ES).
//
// The Spanish end of a building job is one chain of dated acts: the direccion
// facultativa signs the certificado final de obra, the acta de recepcion is
// signed with or without reservas, the guarantee periods of the Ley de
// Ordenacion de la Edificacion run from that date, and the libro del edificio
// is handed to the owner with the instructions they will actually operate from.
//
// The warranty register ships two statutory limitation regimes and both are
// German, so there is no Spanish preset to pick. The module is built for that:
// an entry with no regime derives nothing and rewrites nothing, and the agreed
// period is entered by hand. The case says so rather than implying a preset.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "close-the-works-and-hand-over-the-libro-del-edificio",
  order: 1148,
  region: "ES",
  category: "handover",
  companyTypes: ["general-contractor", "developer-client", "owner-operator"],
  roles: ["project-manager", "document-controller", "contract-administrator"],
  icon: "BookOpen",
  titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.title",
  titleDefault: "Close the works and hand over the libro del edificio",
  descKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.desc",
  descDefault:
    "Get the certificado final de obra signed, take the acta de recepcion with its reservas written down, start the three guarantee periods from that date, assemble the libro del edificio and hand the owner instructions they can actually run the building from.",
  longDescKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.longdesc",
  longDescDefault:
    "Everything at the Spanish end of a job hangs off one date. The certificado final de obra is signed by both members of the direccion facultativa, the acta de recepcion follows it, and from the recepcion the guarantee periods run: one year for defects in the finishes, three for those affecting habitability, ten for those touching structure. The libro del edificio is delivered to the owner and it is not a formality, because it is the document the community will still be reading in fifteen years when a facade repair has to be justified. Two things are worth doing deliberately. Write the reservas into the acta instead of agreeing them in the room, because an acta with reservas suspends nothing except the parts it names. And enter the guarantee periods as dated entries rather than trusting anybody to remember which of the three applies, since the register ships no Spanish regime and will not invent one for you.",
  estMinutes: 20,
  steps: [
    {
      id: "certificate",
      icon: "Signature",
      inputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.in.works",
          label: "Completed works",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.in.parties",
          label: "Direccion facultativa, both roles",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.out.signed",
          label: "Signed completion certificate",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.out.trail",
          label: "Signature trail with dates",
        },
      ],
      titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.title",
      titleDefault: "Get the certificado final de obra signed",
      whatKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.what",
      whatDefault:
        "Send the certificado final de obra for signature by both members of the direccion facultativa, the one who directed the works and the one who directed their execution. Keep the record of who signed and when.",
      whyKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.certificate.why",
      whyDefault:
        "Nothing downstream can start without it: not the recepcion, not the licencia de primera ocupacion, not the release of retention. It is also the point where an outstanding item still gets fixed quickly, because everybody wants the same signature.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "reception",
      icon: "Handshake",
      inputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.in.certificate",
          label: "Signed completion certificate",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.in.snags",
          label: "Outstanding items list",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.out.acta",
          label: "Acta de recepcion with its date",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.out.reservas",
          label: "Reservas written down, not agreed",
        },
      ],
      titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.title",
      titleDefault: "Take the recepcion with the reservas written into it",
      whatKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.what",
      whatDefault:
        "Work the closeout checklist to the point where the package is genuinely complete, then record the acta de recepcion with its date and any reservas set out item by item, along with the period allowed to clear them. Article 6 of the LOE gives the promotor thirty days from the written notice of completion to receive the works or refuse them with reasons, and after that they count as received without reservas; on a public contract article 243 LCSP makes it a formal act with the Administration's representative and the direccion facultativa within a month of completion.",
      whyKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.reception.why",
      whyDefault:
        "A recepcion taken with a vague reserva about finishes is a recepcion where every later disagreement is about what was meant. Written item by item, the reserva names what is outstanding and the rest of the building is received, which is what both sides actually want.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "guarantees",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.in.date",
          label: "Acta de recepcion date",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.in.elements",
          label: "Elements and work packages",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.out.register",
          label: "Warranty register entries",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.out.dates",
          label: "Guarantee end dates on record",
        },
      ],
      titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.title",
      titleDefault: "Start the guarantee periods from that date",
      whatKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.what",
      whatDefault:
        "Enter the guarantee periods by hand against the recepcion date: twelve months for defects in the finishes, thirty-six for those affecting habitability, one hundred and twenty for those touching structure. The register ships no Spanish regime, so leave the regime unset and let the period you entered stand as entered.",
      whyKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.guarantees.why",
      whyDefault:
        "The three periods are the reason a defect reported in year four is a different conversation from the same defect in year two, and nobody reconstructs that from memory. Entered as dates, the register answers it; left to be worked out later, it becomes an argument between people who each remember a different rule.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "assemble",
      icon: "FileStack",
      inputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.in.asbuilt",
          label: "As-built drawings and project file",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.in.certificates",
          label: "Certificates and guarantees",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.out.pack",
          label: "Libro del edificio document pack",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.out.index",
          label: "Index of what is inside it",
        },
      ],
      titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.title",
      titleDefault: "Assemble the libro del edificio",
      whatKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.what",
      whatDefault:
        "Gather what the libro has to carry: the project as built, the acta de recepcion, the list of the parties who took part with their details, the certificates and guarantees, and the instructions for use and maintenance. File it as one indexed set rather than as a folder somebody has to interpret.",
      whyKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.assemble.why",
      whyDefault:
        "The libro is read by people who were not there, years later, usually because something has failed. An index that says what is inside is what turns it from an archive into a document, and the party list is what tells the community who to write to when the ten-year period still has time on it.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "handover",
      icon: "Building2",
      inputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.in.pack",
          label: "Libro del edificio document pack",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.in.equipment",
          label: "Installed plant and equipment",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.out.register",
          label: "Asset register the owner can use",
        },
        {
          labelKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.out.schedule",
          label: "Maintenance schedule per asset",
        },
      ],
      titleKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.title",
      titleDefault: "Hand over instructions the owner can run the building on",
      whatKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.what",
      whatDefault:
        "Load the plant and equipment into the asset register with its location, its guarantee end date and the maintenance the instructions require, so the use and maintenance section of the libro becomes a list of things due rather than a chapter.",
      whyKey: "cases.close_the_works_and_hand_over_the_libro_del_edificio.step.handover.why",
      whyDefault:
        "A guarantee is lost far more often through maintenance nobody did than through a defect nobody reported. The register is what makes the difference visible in the first year, while the periods still have most of their time left and the contractor is still answering the phone.",
      moduleLabel: "Building Assets (FM)",
      moduleLabelKey: "nav.assets",
      to: "/assets",
    },
  ],
};

export default playbook;
