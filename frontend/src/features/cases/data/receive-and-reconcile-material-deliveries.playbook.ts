// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Receive and reconcile material deliveries".
//
// Book a delivery in at the gate, check quantity and condition against the
// order, reconcile against the buying schedule and update site stock. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "receive-and-reconcile-material-deliveries",
  order: 1017,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  icon: "Truck",
  titleKey: "cases.receive_and_reconcile_material_deliveries.title",
  titleDefault: "Receive and reconcile material deliveries",
  descKey: "cases.receive_and_reconcile_material_deliveries.desc",
  descDefault:
    "Book a delivery in at the gate, check quantity and condition against the order, reconcile what arrived against the buying schedule and update site stock so the crew knows what is on the ground.",
  longDescKey: "cases.receive_and_reconcile_material_deliveries.longdesc",
  longDescDefault:
    "The delivery gate is where money and programme meet the real world. A short or damaged load waved through becomes a stopped crew and an argument over an invoice weeks later. Booking every delivery against its order at the moment it lands is the cheapest control on site.",
  estMinutes: 9,
  steps: [
    {
      id: "book",
      icon: "Truck",
      inputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.book.in.delivery", label: "Arriving delivery" },
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.book.in.order", label: "Purchase order" },
      ],
      outputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.book.out.booked", label: "Booked-in record" },
      ],
      titleKey: "cases.receive_and_reconcile_material_deliveries.step.book.title",
      titleDefault: "Book the delivery in",
      whatKey: "cases.receive_and_reconcile_material_deliveries.step.book.what",
      whatDefault:
        "Book the delivery in against its order as it arrives, capturing the delivery note, the date and time and a photo of the load before it is broken down.",
      whyKey: "cases.receive_and_reconcile_material_deliveries.step.book.why",
      whyDefault:
        "A delivery not recorded at the gate is a delivery you cannot prove arrived or dispute if it did not. The booking is the record everything downstream leans on.",
      moduleLabel: "Site Inventory",
      moduleLabelKey: "nav.site_inventory",
      to: "/projects/:projectId/site-inventory",
    },
    {
      id: "check",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.check.in.booked", label: "Booked delivery" },
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.check.in.note", label: "Delivery note" },
      ],
      outputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.check.out.checked", label: "Checked and flagged" },
      ],
      titleKey: "cases.receive_and_reconcile_material_deliveries.step.check.title",
      titleDefault: "Check quantity and condition",
      whatKey: "cases.receive_and_reconcile_material_deliveries.step.check.what",
      whatDefault:
        "Check the quantity and condition against the delivery note and the order, and flag any shortage, breakage or wrong item on the spot before you sign for it.",
      whyKey: "cases.receive_and_reconcile_material_deliveries.step.check.why",
      whyDefault:
        "Signing for a load clean and finding it short later leaves you carrying the loss. Flagging the problem at the gate, in the record, is what keeps the supplier on the hook.",
      moduleLabel: "Site Inventory",
      moduleLabelKey: "nav.site_inventory",
      to: "/projects/:projectId/site-inventory",
    },
    {
      id: "reconcile",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.in.checked", label: "Checked delivery" },
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.in.schedule", label: "Buying schedule" },
      ],
      outputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.out.status", label: "Delivered-versus-ordered" },
      ],
      titleKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.title",
      titleDefault: "Reconcile against the schedule",
      whatKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.what",
      whatDefault:
        "Reconcile what arrived against the buying schedule, so you can see what is still outstanding on each order and chase a shortfall before it stops the work.",
      whyKey: "cases.receive_and_reconcile_material_deliveries.step.reconcile.why",
      whyDefault:
        "The buying schedule is the plan; deliveries are the reality. Reconciling the two is how you catch the missing half of an order in time to expedite it rather than idle a gang.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "stock",
      icon: "Warehouse",
      inputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.stock.in.status", label: "Reconciled delivery" },
      ],
      outputs: [
        { labelKey: "cases.receive_and_reconcile_material_deliveries.step.stock.out.stock", label: "Updated site stock" },
      ],
      titleKey: "cases.receive_and_reconcile_material_deliveries.step.stock.title",
      titleDefault: "Update site stock",
      whatKey: "cases.receive_and_reconcile_material_deliveries.step.stock.what",
      whatDefault:
        "Add the accepted materials to site stock so the team can see what is held, where it is and what is committed against the next pour or lift.",
      whyKey: "cases.receive_and_reconcile_material_deliveries.step.stock.why",
      whyDefault:
        "Knowing what is on the ground stops double ordering and the panic buy at premium price. Live stock is also what lets you protect against theft and over-delivery of perishables.",
      moduleLabel: "Site Inventory",
      moduleLabelKey: "nav.site_inventory",
      to: "/projects/:projectId/site-inventory",
    },
  ],
};

export default playbook;
