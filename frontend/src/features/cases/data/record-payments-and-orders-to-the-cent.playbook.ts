// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Record payments and orders to the cent".
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "record-payments-and-orders-to-the-cent",
  order: 1704,
  category: "commercial",
  stage: "build",
  companyTypes: ["developer-client", "general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "commercial-manager"],
  icon: "ReceiptEuro",
  titleKey: "cases.record_payments_and_orders_to_the_cent.title",
  titleDefault: "Record payments and orders to the cent",
  descKey: "cases.record_payments_and_orders_to_the_cent.desc",
  descDefault:
    "Enter purchase orders, invoices and payments to the cent, match each invoice to its order, and see where the order lands in cost control and where its certified and paid figures come from.",
  longDescKey: "cases.record_payments_and_orders_to_the_cent.longdesc",
  longDescDefault:
    "Rounding a purchase order or a payment by a few cents seems harmless until the account does not reconcile and someone spends a day looking for the difference. The platform stores money as exact decimals and rounds each line to the cent once, so the order, the invoice and the payment agree to the cent. This case walks the chain once: order, invoice against the order, payment, and the order's place in cost control.",
  estMinutes: 10,
  steps: [
    {
      id: "order",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.order.in.offer", label: "Supplier offer" },
      ],
      outputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.order.out.po", label: "Purchase order with exact amounts" },
      ],
      titleKey: "cases.record_payments_and_orders_to_the_cent.step.order.title",
      titleDefault: "Issue the order with exact amounts",
      whatKey: "cases.record_payments_and_orders_to_the_cent.step.order.what",
      whatDefault:
        "In Procurement, issue the purchase order with the exact quantities and unit prices from the offer, including the cents.",
      whyKey: "cases.record_payments_and_orders_to_the_cent.step.order.why",
      whyDefault:
        "The order is the reference every invoice is checked against. An order rounded at entry makes every later match look wrong.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "invoice",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.invoice.in.po", label: "Purchase order with exact amounts" },
      ],
      outputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.invoice.out.invoice", label: "Invoice matched to its order" },
      ],
      titleKey: "cases.record_payments_and_orders_to_the_cent.step.invoice.title",
      titleDefault: "Book the invoice against the order",
      whatKey: "cases.record_payments_and_orders_to_the_cent.step.invoice.what",
      whatDefault:
        "In Finance, create a New Invoice as payable, choose the supplier, pick its purchase order and enter the lines with quantity, unit rate and VAT so the Net matches the invoice to the cent.",
      whyKey: "cases.record_payments_and_orders_to_the_cent.step.invoice.why",
      whyDefault:
        "Matching the invoice to its order shows at once whether the supplier billed more than was ordered.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "payment",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.payment.in.invoice", label: "Invoice matched to its order" },
      ],
      outputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.payment.out.payment", label: "Payment on record" },
      ],
      titleKey: "cases.record_payments_and_orders_to_the_cent.step.payment.title",
      titleDefault: "Record the payment",
      whatKey: "cases.record_payments_and_orders_to_the_cent.step.payment.what",
      whatDefault:
        "Once the invoice is approved, press Mark Paid. It records the payment for the whole open amount, less any retention, with today's date.",
      whyKey: "cases.record_payments_and_orders_to_the_cent.step.payment.why",
      whyDefault:
        "The amount paid has to equal the bank statement to the cent, or the reconciliation at month end turns into a search.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "check",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.check.in.payment", label: "Payment on record" },
      ],
      outputs: [
        { labelKey: "cases.record_payments_and_orders_to_the_cent.step.check.out.agreed", label: "Order traced into cost control" },
      ],
      titleKey: "cases.record_payments_and_orders_to_the_cent.step.check.title",
      titleDefault: "Find the order in cost control",
      whatKey: "cases.record_payments_and_orders_to_the_cent.step.check.what",
      whatDefault:
        "Open Cost control and check the order under awarded on its cost line. Certified and paid there come from certified subcontract claims less retention, not from Finance payments, so reconcile supplier payments in Finance.",
      whyKey: "cases.record_payments_and_orders_to_the_cent.step.check.why",
      whyDefault:
        "Knowing which figure comes from where is what lets the forecast and the accounts be compared without a search for the difference.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
  ],
};

export default playbook;
