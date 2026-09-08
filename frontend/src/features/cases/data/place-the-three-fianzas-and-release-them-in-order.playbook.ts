// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Place the three fianzas and release them in order" (MX).
//
// Hand written, not composed. A Mexican public works contract is secured by
// three separate fianzas that answer for three separate risks at three
// separate times, and treating them as one item called "the bond" is how a
// contractor ends up paying premiums on security nobody can cancel and
// leaving an increase unsecured at the same time.
//
//   fianza de anticipo      the money handed over before any work is done
//   fianza de cumplimiento  performance of the contract itself
//   fianza de vicios ocultos defects and hidden vices after the works are
//                           received, which article 66 LOPSRM sets at twelve
//                           months and lets the contractor secure in one of
//                           several forms
//
// The product has no bond register of its own. What it has is a contract
// record, a deadline register and a document store, which between them hold
// the amount, the dates and the paper. The case walks those and does not
// pretend to issue a fianza: that is done by an afianzadora, outside.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "place-the-three-fianzas-and-release-them-in-order",
  order: 1266,
  region: "MX",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "developer-client"],
  roles: ["contract-administrator", "commercial-manager", "finance-manager"],
  icon: "ShieldCheck",
  titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.title",
  titleDefault: "Place the three fianzas and release them in order",
  descKey: "cases.place_the_three_fianzas_and_release_them_in_order.desc",
  descDefault:
    "Post the fianza de cumplimiento inside the days the award allows, secure the anticipo before the money moves, keep all three bonds in a register with their dates, endorse them when a convenio modificatorio moves the contract, and cancel each one on the event that actually ends its risk.",
  longDescKey: "cases.place_the_three_fianzas_and_release_them_in_order.longdesc",
  longDescDefault:
    "Three bonds, three risks, three release events, and confusing them costs money in both directions. The fianza de cumplimiento answers for the performance of the contract and has to be delivered within the days that follow the notification of the award, fifteen where the convocatoria sets no other period, which is short enough that the afianzadora has to be lined up before the fallo rather than after it. The fianza de anticipo answers for something else entirely, the money handed over before any work exists, so it covers the whole of the advance and it lives until the advance has been amortised, not until the works are finished. The fianza de vicios ocultos answers for a risk that only begins where the other two end: article 66 LOPSRM makes the contractor responsible for defects and hidden vices for twelve months after the works are received, and lets it secure them with a fianza, an irrevocable letter of credit or an amount placed in trust. Each of the three ends on its own event, and a bond nobody cancels goes on charging a premium for a risk that stopped existing.",
  estMinutes: 16,
  steps: [
    {
      id: "cumplimiento",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.in.fallo",
          label: "Notification of the award",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.in.terms",
          label: "Bond terms the convocatoria sets",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.out.bond",
          label: "Fianza de cumplimiento delivered",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.out.dates",
          label: "Delivery date against the deadline",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.title",
      titleDefault: "Deliver the fianza de cumplimiento inside the days you have",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.what",
      whatDefault:
        "As soon as the fallo is notified, have the afianzadora issue the fianza de cumplimiento on the terms the convocatoria set, in favour of the dependencia, and deliver it. The period is fifteen days following the notification of the award where the convocatoria does not name another one. Record the delivery date on the contract, not only the date on the bond.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cumplimiento.why",
      whyDefault:
        "This is one of the few deadlines on a Mexican public contract that can cost you the contract itself rather than money, and it lands in the week everyone is celebrating. It is short by design and it starts on a notification rather than on a signature, so a firm that waits for the contract to be drafted before calling the afianzadora has already spent most of it.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "anticipo",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.in.amount",
          label: "Anticipo the contract grants",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.in.schedule",
          label: "When each part is to be paid",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.out.bond",
          label: "Fianza de anticipo in place",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.out.condition",
          label: "Payment released against the security",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.title",
      titleDefault: "Secure the anticipo before the money moves",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.what",
      whatDefault:
        "Put the fianza de anticipo in place for the whole of the advance before any part of it is paid over, and record it against the anticipo rather than against the contract in general. Where the anticipo is granted in parts, make sure the security covers the part being released.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.anticipo.why",
      whyDefault:
        "It secures a different thing from the fianza de cumplimiento, which is why it exists separately: money handed over before there is any work to look at. That also decides when it ends. It follows the amortizacion, not the completion of the works, so on a job that finishes with the advance not fully repaid this bond outlives the project and nobody expects it to.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "register",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.in.bonds",
          label: "Bonds issued so far",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.in.events",
          label: "Events that end each risk",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.out.register",
          label: "One register, three bonds, dated",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.out.owner",
          label: "An owner against each date",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.title",
      titleDefault: "Keep the three in one register with their dates",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.what",
      whatDefault:
        "Enter each bond once with the four things anybody will ever ask: what it secures, its amount, the afianzadora and policy number, and the event that ends it. Then set the dates that follow from those events, so the register is what gets read rather than the folder of PDFs.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.register.why",
      whyDefault:
        "Bonds fail quietly in both directions. One that expires while the risk is still live leaves the works unsecured and the dependencia entitled to say so; one that outlives its risk goes on charging a premium every year until somebody notices, which on a portfolio of finished jobs is a real number nobody has ever added up.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "endorse",
      icon: "GitCompare",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.in.convenio",
          label: "Convenio modificatorio",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.in.current",
          label: "Bonds as currently issued",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.out.endorsed",
          label: "Endorsement matching the new amount",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.out.gap",
          label: "No unsecured increase left open",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.title",
      titleDefault: "Endorse the bonds when a convenio moves the contract",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.what",
      whatDefault:
        "Every convenio modificatorio that raises the contract amount or extends the term is a change to the security as well as to the works. Have the fianza de cumplimiento endorsed for the new amount and the new period, and update the register from the endorsement rather than from the convenio.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.endorse.why",
      whyDefault:
        "An increase agreed but not endorsed leaves the extra work unsecured, which is a finding the moment anybody audits the file and an argument the dependencia can use to hold an estimacion. It is invisible while it lasts, because the convenio is signed, the works are proceeding and the original bond is still perfectly valid for the amount it was written for.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "vicios",
      icon: "BadgeCheck",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.in.recepcion",
          label: "Date set for the recepcion fisica",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.in.executed",
          label: "Monto total ejercido",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.out.security",
          label: "Vicios ocultos security in place",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.out.window",
          label: "Twelve month period diarised",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.title",
      titleDefault: "Put up the vicios ocultos security before the acta",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.what",
      whatDefault:
        "Before the acta de entrega-recepcion is signed, provide the guarantee article 66 LOPSRM requires against defects and hidden vices for the twelve months that follow. The article lets you choose the form: a fianza, an irrevocable letter of credit, or an amount placed in trust. Choose it on cash rather than habit, and diarise the day the twelve months end.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.vicios.why",
      whyDefault:
        "It has to exist before the works are received, so it is prepared during the busiest fortnight of the job or it delays the acta, and a delayed acta delays the finiquito and everything behind it. The choice of form is worth an hour: a trust deposit ties up cash for a year while a fianza costs a premium, and the right answer depends on which of those the firm has less of.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "cancel",
      icon: "FileCheck2",
      inputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.in.evidence",
          label: "Finiquito and acta administrativa",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.in.balance",
          label: "Anticipo balance at zero",
        },
      ],
      outputs: [
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.out.cancelled",
          label: "Each bond cancelled on its own event",
        },
        {
          labelKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.out.premiums",
          label: "Premiums stopped",
        },
      ],
      titleKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.title",
      titleDefault: "Cancel each bond on the event that ends its risk",
      whatKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.what",
      whatDefault:
        "Release the fianza de anticipo when the advance reaches zero, the fianza de cumplimiento against the finiquito and the acta administrativa that extinguishes the rights and obligations, and the vicios ocultos security when the twelve months are up with no claim outstanding. File the paper the afianzadora needs against each one, because a cancellation is granted on evidence rather than on a request.",
      whyKey: "cases.place_the_three_fianzas_and_release_them_in_order.step.cancel.why",
      whyDefault:
        "Nobody is chasing you to stop paying, so this is the step that gets skipped on every job that ends well. The cost is not only the premium: an open bond consumes the line the afianzadora will extend you, and a firm bidding its next contract discovers its capacity is committed to three jobs it finished years ago.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
