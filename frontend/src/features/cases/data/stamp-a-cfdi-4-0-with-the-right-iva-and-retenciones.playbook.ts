// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Stamp a CFDI 4.0 with the right IVA and retenciones" (MX).
//
// Hand written, not composed. The existing MX progress-payment case raises a
// CFDI as its last step but says nothing about what has to be true for the
// stamp to be granted, what rate the site's region carries, what has to be
// withheld, or what happens after the invoice is paid. Those are the parts a
// Mexican administracion spends its month on, so they get a case.
//
// What the platform holds and what it does not. The e-invoice clearance
// module carries Mexico as a clearance regime (CFDI 4.0, identifier UUID or
// Folio Fiscal, document format cfdi_4_0, issuer and receiver RFC, uso CFDI
// and regimen fiscal) and records the submission and its answer. It does NOT
// generate the CFDI XML: the stamp itself is applied by a certified provider,
// a PAC, outside the product, and the EN 16931 engine does not cover CFDI.
// The tax rate registry holds the Mexican IVA rates and the withholding
// module holds the retenciones. The case walks those and says plainly where
// the boundary is.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "stamp-a-cfdi-4-0-with-the-right-iva-and-retenciones",
  order: 1262,
  region: "MX",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "contract-administrator"],
  icon: "Stamp",
  titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.title",
  titleDefault: "Stamp a CFDI 4.0 with the right IVA and retenciones",
  descKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.desc",
  descDefault:
    "Get the fiscal identity of both parties right before anything is issued, charge IVA at the rate the site's region carries, withhold the IVA and ISR the law makes you withhold, have the document stamped, and follow a PPD invoice with its complemento de pago inside the deadline.",
  longDescKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.longdesc",
  longDescDefault:
    "An invoice that was not stamped is not a late invoice, it is not an invoice. The stamp, the timbrado, is applied by a certified provider and the UUID it returns is what makes the document deductible for your client, which is why a client who cannot deduct will not pay. CFDI 4.0 tightened the part most firms get wrong: the receiver's name, postcode and regimen fiscal are validated against the SAT register, so one character out of place fails the whole batch rather than one line of it. Everything downstream inherits that discipline. A stamped document is corrected by cancelling it and issuing a replacement, never by editing it, and article 29-A of the Codigo Fiscal de la Federacion closes the cancellation window at the month the annual return for the year of issue falls due. Right before stamping is cheap. Right afterwards is a cancellation, an acceptance from the buyer and a reissue.",
  estMinutes: 18,
  steps: [
    {
      id: "fiscaldata",
      icon: "KeyRound",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.in.constancia",
          label: "Constancia de situacion fiscal, both parties",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.in.cert",
          label: "Certificado de sello digital",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.out.issuer",
          label: "Issuer RFC, regimen fiscal and codigo postal",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.out.receiver",
          label: "Receiver record matching the SAT register",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.title",
      titleDefault: "Record the fiscal identity the stamp will be checked against",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.what",
      whatDefault:
        "Record, for the issuer and for every client you invoice, the RFC, the nombre or razon social spelled exactly as the constancia de situacion fiscal spells it, the regimen fiscal code and the codigo postal of the domicilio fiscal. An RFC has twelve characters for a persona moral and thirteen for a persona fisica: a letter prefix, a six digit date and a three character homoclave.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.fiscaldata.why",
      whyDefault:
        "CFDI 4.0 validates the receiver's name, postcode and regimen fiscal against the SAT register at the moment of stamping, which version 3.3 did not. That turns a client who moved office, or a razon social typed with an abbreviation, into a rejection for every invoice you raise on them, and it is discovered on the day the month is invoiced rather than in the week there was time to fix it.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings",
    },
    {
      id: "iva",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.in.location",
          label: "Where the works are",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.in.registration",
          label: "Border region registration, if held",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.out.rate",
          label: "IVA rate chosen and recorded",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.out.reason",
          label: "Reason the rate applies",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.title",
      titleDefault: "Charge IVA at the rate the region actually carries",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.what",
      whatDefault:
        "Set the IVA rate on the project: sixteen percent as the standard rate under the Ley del Impuesto al Valor Agregado, eight percent where the northern or southern border region stimulus decrees apply and the issuer is registered for them, zero where the law zero rates the supply. Record which of the three it is and why, on the project rather than in somebody's head.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.iva.why",
      whyDefault:
        "The eight percent border rate is a stimulus with conditions attached, not a property of the map: it applies to a taxpayer registered for it, not to any works that happen to sit in a border state. Charged without the registration it is an underpayment the SAT collects later with surcharges, and charged at sixteen where eight applied it is a price your competitor down the road did not have to quote.",
      moduleLabel: "Tax Rates",
      moduleLabelKey: "nav.tax_rates",
      to: "/tax-rates",
    },
    {
      id: "retenciones",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.in.supplier",
          label: "Supplier regime and service type",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.in.contract",
          label: "What the subcontract actually provides",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.out.decision",
          label: "Retencion decision per supplier",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.out.amounts",
          label: "IVA and ISR withheld on the payment",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.title",
      titleDefault: "Withhold what the law makes you withhold",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.what",
      whatDefault:
        "Decide, per supplier, whether a retencion applies and record the decision either way. Article 1-A of the Ley del Impuesto al Valor Agregado is where the two common ones live: fraction IV withholds six percent of IVA on services that put personnel at the contratante's disposal, and fraction II withholds on payments to a persona fisica, which the Ley del Impuesto sobre la Renta pairs with an ISR retention of its own. The rate depends on the supplier's regime and on what the contract really provides, so the platform holds the figure you confirm rather than applying one for you.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.retenciones.why",
      whyDefault:
        "The retencion is the contratante's liability, not the supplier's. Failing to withhold does not leave the money with the subcontractor and the problem with them, it leaves you owing the SAT an amount you already paid away, and it costs you the deduction on the expense as well. Recording a deliberate decision not to withhold is worth as much as the withholding itself, because the question always comes back months later.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "issue",
      icon: "ReceiptText",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.in.authorised",
          label: "Authorised estimacion",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.in.deductions",
          label: "Amortizacion, fondo de garantia, retenciones",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.out.draft",
          label: "CFDI de ingreso ready to stamp",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.out.method",
          label: "Uso CFDI and metodo de pago set",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.title",
      titleDefault: "Raise the CFDI against the authorised figure",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.what",
      whatDefault:
        "Build the CFDI de ingreso from the authorised estimacion, carrying the amortizacion del anticipo, the fondo de garantia and any retencion as their own concepts rather than netted into the price. Set the uso CFDI the client asks for, and set metodo de pago honestly: PUE when the money arrives in one payment inside the same period, PPD when it does not.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.issue.why",
      whyDefault:
        "Metodo de pago is the field that decides how much work the rest of the year is. PUE closes the transaction on its own; PPD obliges you to issue a complemento de pago for every payment received against it. Marking a PPD invoice as PUE because the money was expected quickly leaves a stamped document saying it was paid on a day it was not, and the correction is a cancellation rather than an edit.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "stamp",
      icon: "Stamp",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.in.draft",
          label: "CFDI ready to stamp",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.in.pac",
          label: "Certified provider and its answer",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.out.uuid",
          label: "UUID or Folio Fiscal recorded",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.out.state",
          label: "Submission state against the invoice",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.title",
      titleDefault: "Get it stamped and keep the UUID against the invoice",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.what",
      whatDefault:
        "Send the document for timbrado and record what came back against the invoice: the UUID, the date and the state of the submission. The stamp is applied by a certified provider rather than by the tax authority directly, and the product records that answer rather than producing the CFDI XML itself, so the clearance record is what tells you which invoices are real and which are drafts with a number on them.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.stamp.why",
      whyDefault:
        "The UUID is the whole point of the exercise: it is what makes the document deductible for your client, and a client who cannot deduct will find a reason not to pay. A rejected stamp is silent unless somebody is watching the answers, and the way it usually surfaces is a client asking for an invoice you believe you sent them three weeks ago.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
    {
      id: "complemento",
      icon: "Receipt",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.in.ppd",
          label: "PPD invoices outstanding",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.in.receipts",
          label: "Payments actually received",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.out.rep",
          label: "Complemento de pago stamped",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.out.closed",
          label: "Invoice closed against the money",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.title",
      titleDefault: "Follow a PPD invoice with its complemento de pago",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.what",
      whatDefault:
        "For every payment received against a PPD invoice, issue a CFDI carrying the complemento para recepcion de pagos, referencing the UUID it settles and the amount. The Resolucion Miscelanea Fiscal sets the deadline at the fifth natural day of the month following the month the payment fell in, and natural means it does not move for a weekend or a holiday.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.complemento.why",
      whyDefault:
        "The complemento is what proves the income was actually received, so an unissued one leaves the original invoice hanging with no cash behind it in the eyes of the authority. It is also the piece a busy site forgets, because the money has arrived and the job feels finished, and the fifth of the month arrives during the same week the next estimacion is being measured.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
    {
      id: "correct",
      icon: "GitCompare",
      inputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.in.wrong",
          label: "Stamped CFDI with a wrong figure",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.in.motivo",
          label: "Motivo de cancelacion from the catalogue",
        },
      ],
      outputs: [
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.out.cancelled",
          label: "Cancellation with its motivo on record",
        },
        {
          labelKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.out.replacement",
          label: "Replacement CFDI linked to the old UUID",
        },
      ],
      titleKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.title",
      titleDefault: "Correct by cancelling and replacing, never by editing",
      whatKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.what",
      whatDefault:
        "When a stamped figure is wrong, cancel the CFDI with a motivo from the SAT catalogue and issue the replacement, relating the new document to the UUID of the one it replaces. The buyer's acceptance is part of the process for the motivos that require it, so the cancellation is a conversation with a date on it rather than a button.",
      whyKey: "cases.stamp_a_cfdi_4_0_with_the_right_iva_and_retenciones.step.correct.why",
      whyDefault:
        "Article 29-A of the Codigo Fiscal de la Federacion closes the window at the month the annual return for the year the CFDI was issued falls due, so a December document and a January one have very different amounts of time left. Firms that treat cancellation as always available discover the difference in the same week they discover the error, and by then the only remaining fix is a commercial one.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
