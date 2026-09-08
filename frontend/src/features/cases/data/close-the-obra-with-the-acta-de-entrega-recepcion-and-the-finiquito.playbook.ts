// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Close the obra with the acta de entrega-recepcion and the
// finiquito" (MX).
//
// Hand written, not composed. A LOPSRM contract does not end when the works
// end. It ends through a sequence of instruments in a fixed order, and each
// one is the precondition of the next: the bitacora de obra is closed, the
// contractor gives notice that the works are terminated, the dependencia
// verifies and receives them in an acta de entrega-recepcion, the parties
// settle everything in a finiquito, and the contract is finally extinguished
// by an acta administrativa. The twelve months of vicios ocultos that
// article 66 LOPSRM imposes then run past all of it.
//
// The bitacora carries the whole build phase into this case, which is why it
// is the first step rather than a case of its own: what it recorded is what
// the finiquito is argued from. The product holds it as the project diary,
// the receipt as close-out, the settlement as finance and the twelve months
// as the defects liability register. The formal instruments are signed
// outside, and where the bitacora is kept electronically by the convocante
// that system is outside too.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "close-the-obra-with-the-acta-de-entrega-recepcion-and-the-finiquito",
  order: 1268,
  region: "MX",
  category: "handover",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["contract-administrator", "site-manager", "commercial-manager"],
  icon: "Handshake",
  titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.title",
  titleDefault: "Close the obra with the acta de entrega-recepcion and the finiquito",
  descKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.desc",
  descDefault:
    "Close the bitacora, give notice that the works are terminated, clear the observations, sign the acta de entrega-recepcion, settle everything in the finiquito, extinguish the contract by acta administrativa and then run the twelve months of vicios ocultos that outlive all of it.",
  longDescKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.longdesc",
  longDescDefault:
    "Closing a Mexican public works contract is a sequence, not an event, and skipping a step does not save time, it stops the sequence. The bitacora de obra is the instrument of communication between the parties under the reglamento of the LOPSRM, so it is where every instruction, every suspension and every extension of time was recorded while the works were running, and closing it is what fixes that record. The contractor then gives written notice of termination, the dependencia verifies and receives the works in an acta de entrega-recepcion, and the parties settle in a finiquito that has to account for everything at once: estimaciones paid, ajuste de costos claimed and resolved, the anticipo amortised to zero, retenciones, penas convencionales and any work received but not yet paid. The acta administrativa that follows extinguishes the rights and obligations of both parties, which is the document that lets the fianza de cumplimiento be cancelled. And none of it ends the vicios ocultos period: article 66 LOPSRM runs twelve months from the reception, secured before the acta was ever signed.",
  estMinutes: 22,
  steps: [
    {
      id: "bitacora",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.in.notes",
          label: "Notas de bitacora across the job",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.in.open",
          label: "Matters still open in it",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.out.closed",
          label: "Bitacora closed with its nota de cierre",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.out.index",
          label: "Index of the notes the finiquito relies on",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.title",
      titleDefault: "Close the bitacora and index what it proves",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.what",
      whatDefault:
        "Read the bitacora from the first note to the last and close it with the nota de cierre. Before you do, list the notes the finiquito will lean on: the instructions behind conceptos extraordinarios, the suspensions, the extensions of time, and anything left answered by silence. Where a matter is still open, close it in a note now rather than leaving it to be argued after the record is shut.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.bitacora.why",
      whyDefault:
        "The bitacora is the instrument of communication between the parties under the reglamento of the LOPSRM, which makes it the record both sides are held to and not a site notebook. Everything you will want to say at the finiquito has to already be in it, because a note added after the works finished carries no weight and a claim with no note behind it carries none either.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "aviso",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.in.complete",
          label: "Works complete against the catalogo",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.in.tests",
          label: "Tests and commissioning results",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.out.notice",
          label: "Written notice of termination, dated",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.out.verification",
          label: "Verification period running",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.title",
      titleDefault: "Give written notice that the works are terminated",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.what",
      whatDefault:
        "Notify the dependencia in writing that the works are terminated, attaching what it needs to verify them, and record the date the notice went and the date it was received. The verification period the contract sets runs from that receipt, so it is a dated fact rather than a courtesy.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.aviso.why",
      whyDefault:
        "Everything after this step is counted from a date, and the notice is the first of them. Without it the works can be complete for months while the file says nothing happened, and the contractor has no way to show it was waiting rather than late. A phone call to the residencia is not a notice, however well it was received.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "observations",
      icon: "ListChecks",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.in.walk",
          label: "Observations from the verification walk",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.in.spec",
          label: "Especificaciones the work is judged against",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.out.list",
          label: "Observations with an owner and a date",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.out.cleared",
          label: "Each one cleared with its evidence",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.title",
      titleDefault: "Clear the observations before the reception, not after",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.what",
      whatDefault:
        "Take the observations raised on the verification walk as a list with an owner, a date and the evidence that closes each one, and work it down before the acta is signed. Where an observation is not defective work but a change the dependencia is asking for, say so at the time and price it, rather than absorbing it to get the acta signed.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.observations.why",
      whyDefault:
        "Observations left open at the reception do not disappear, they move into the twelve months of vicios ocultos, where they are secured by your own guarantee and dealt with by a crew that has been demobilised. The same repair costs a fraction of the price while there is still a site, and the pressure to sign the acta first and fix afterwards is at its highest in exactly that week.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "acta",
      icon: "Handshake",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.in.cleared",
          label: "Observations cleared",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.in.security",
          label: "Vicios ocultos security in place",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.out.acta",
          label: "Acta de entrega-recepcion signed",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.out.handover",
          label: "Manuals, warranties and as-built handed over",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.title",
      titleDefault: "Sign the acta de entrega-recepcion fisica",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.what",
      whatDefault:
        "Receive the works formally: the acta de entrega-recepcion with the parties, the date, the works received and the state they were received in, and with it the handover pack, the as-built drawings, the manuals, the equipment warranties and the test results. The guarantee against vicios ocultos has to already be in the dependencia's hands, because article 66 LOPSRM wants it before the works are received rather than after.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.acta.why",
      whyDefault:
        "This is the date the rest of the close-out is measured from and the date the twelve months of vicios ocultos start, so it is worth an argument to get it right on the paper. It is also the point where risk moves: after it the works are the dependencia's to operate and yours to answer for, which are two different things and are commonly assumed to be one.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "finiquito",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.in.paid",
          label: "Estimaciones paid to date",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.in.open",
          label: "Anticipo, ajuste, retenciones and penas",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.out.finiquito",
          label: "Finiquito with a single balance",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.out.settlement",
          label: "Final CFDI or credit note raised",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.title",
      titleDefault: "Settle everything at once in the finiquito",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.what",
      whatDefault:
        "Bring the whole contract onto one page within the period the LOPSRM allows after the reception: everything certified and paid, the volumes executed against the catalogo, conceptos extraordinarios authorised, ajuste de costos claimed and resolved, the anticipo amortised, the fondo de garantia, retenciones and any penas convencionales. The result is one balance, owed one way or the other, and the fiscal document that settles it follows the balance.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.finiquito.why",
      whyDefault:
        "The finiquito is where every loose end from three years arrives at once, and it is settled from records rather than from memory: a generador nobody kept, an extraordinario agreed verbally or an ajuste never formally requested is simply not in it. It is also not optional and it does not wait for you. Where one party will not take part, the other may make the finiquito and notify it, so the choice is between being in the room and being told what was decided there.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "extincion",
      icon: "Signature",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.in.finiquito",
          label: "Finiquito agreed and settled",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.in.parties",
          label: "Signatories on both sides",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.out.acta",
          label: "Acta administrativa signed",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.out.release",
          label: "Fianza de cumplimiento clear to cancel",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.title",
      titleDefault: "Extinguish the contract by acta administrativa",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.what",
      whatDefault:
        "Once the finiquito is settled, sign the acta administrativa that gives the rights and obligations of the parties as extinguished, and file it with the contract. Take it straight to the afianzadora, because it is the document that lets the fianza de cumplimiento be cancelled.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.extincion.why",
      whyDefault:
        "This is the step everybody assumes has happened, because the works are handed over, the money is settled and the team has gone. Without it the contract is still formally alive, the fianza de cumplimiento cannot be released, and the bonding capacity it consumes is still committed against a job that ended two years ago.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "vicios",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.in.acta",
          label: "Date of the acta de entrega-recepcion",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.in.defects",
          label: "Defects reported in the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.out.register",
          label: "Defects register for the twelve months",
        },
        {
          labelKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.out.expiry",
          label: "Expiry date and release of the security",
        },
      ],
      titleKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.title",
      titleDefault: "Run the twelve months of vicios ocultos to their end",
      whatKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.what",
      whatDefault:
        "Open a register that runs from the date on the acta for the twelve months article 66 LOPSRM sets, with an owner and a route for anything reported. Record each defect, what was done and whether it was your responsibility or a matter of use and maintenance, and diarise the expiry so the security can be released the week it ends.",
      whyKey: "cases.close_the_obra_with_the_acta_de_entrega_recepcion_and_the_finiquito.step.vicios.why",
      whyDefault:
        "The twelve months are the only part of the contract that is live while nobody is looking at it, and a defect reported to a site email that stopped being read is still a defect you are answerable for. Keeping the register also settles the argument that actually arises, which is almost never whether the fault exists but whether it is a hidden vice or the way the building has been used.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
  ],
};

export default playbook;
