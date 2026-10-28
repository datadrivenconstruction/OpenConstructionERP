// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// procurementGuide - "How it works" content for the Procurement module.
// Consumed by <ModuleGuideButton content={procurementGuide} /> on ProcurementPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const procurementGuide: ModuleGuideContent = {
  titleKey: 'guide.procurement.title',
  titleDefault: 'Procurement',
  introKey: 'guide.procurement.intro',
  introDefault:
    'Procurement is where you commit project spend with a vendor before any invoice arrives. Raise purchase orders, log deliveries as goods receipts, then turn a PO into an invoice so the amount flows into Finance.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.procurement.tabs.title',
      titleDefault: 'Purchase orders and goods receipts',
      bodyKey: 'guide.procurement.tabs.body',
      bodyDefault:
        'The module has two tabs. Purchase Orders lists every order you have raised against the active project, with its vendor, dates, amount and status. Goods Receipts records the deliveries logged against those orders, showing received versus ordered quantities.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.procurement.create.title',
      titleDefault: 'Raise a purchase order',
      bodyKey: 'guide.procurement.create.body',
      bodyDefault:
        'Click New Purchase Order and pick the vendor, the PO type and a delivery date. Add line items with a description, quantity, unit and rate, and each amount totals for you into a subtotal, tax and grand total. Currency defaults to the project currency and the payment terms set the net days.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.procurement.lifecycle.title',
      titleDefault: 'Approve, issue and invoice',
      bodyKey: 'guide.procurement.lifecycle.body',
      bodyDefault:
        'A new order starts as a draft. Approve it to commit the budget in Finance, then Issue it to send it to the vendor. Once issued you can create an invoice straight from the PO, which posts a payable in Finance and pushes the amount through the project budget.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.procurement.match.title',
      titleDefault: 'Three-way match',
      bodyKey: 'guide.procurement.match.body',
      bodyDefault:
        'Each row checks the order against its goods receipts and invoices. The match badge flags whether the line is matched, partial or not yet matched, and warns when a delivery or invoice exceeds what was ordered so you catch over-receipts and over-billing early.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.procurement.vendors.title',
      titleDefault: 'Vendors and retainage',
      bodyKey: 'guide.procurement.vendors.body',
      bodyDefault:
        'Click a vendor name to open its supplier scorecard, and watch for the prequalification badge that flags vendors needing review. When an order withholds retention, a retainage chip appears and managers can release the held amount from the retainage panel.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.procurement.receipts.title',
      titleDefault: 'Logging deliveries',
      bodyKey: 'guide.procurement.receipts.body',
      bodyDefault:
        'Goods receipts capture what actually arrived against a purchase order, each with its own reference, date and received quantity. Use them to confirm a delivery is complete before the invoice is matched and paid.',
    },
  ],
  ctaKey: 'guide.procurement.cta',
  ctaDefault: 'Raise your first purchase order',
};
