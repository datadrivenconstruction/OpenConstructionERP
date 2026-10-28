// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// supplierCatalogsGuide - "How it works" content for the Supplier Catalogs
// module. Consumed by <ModuleGuideButton content={supplierCatalogsGuide} />
// on SupplierCatalogsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const supplierCatalogsGuide: ModuleGuideContent = {
  titleKey: 'guide.supplier_catalogs.title',
  titleDefault: 'Supplier Catalogs',
  introKey: 'guide.supplier_catalogs.intro',
  introDefault:
    'Supplier Catalogs is the vendor and item reference library that purchasing draws from. Keep your suppliers, priced catalog items and warehouse stock here, then let the Procurement module run the live buying workflow against them.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.supplier_catalogs.overview.title',
      titleDefault: 'A reference library, not a buying screen',
      bodyKey: 'guide.supplier_catalogs.overview.body',
      bodyDefault:
        'This page holds the master data behind purchasing: vendors, catalog items and warehouse stock. Raising requisitions, issuing purchase orders and matching invoices happen in the Procurement module, which reads from the records you maintain here.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.supplier_catalogs.tabs.title',
      titleDefault: 'Four tabs, one library',
      bodyKey: 'guide.supplier_catalogs.tabs.body',
      bodyDefault:
        'Switch between Vendors, Catalog, Procurement and Warehouses with the tabs. Vendors, Catalog and Warehouses are editable reference records, while Procurement is a read-only hand-off that links straight into the live purchasing module.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.supplier_catalogs.vendors.title',
      titleDefault: 'Register your vendors',
      bodyKey: 'guide.supplier_catalogs.vendors.body',
      bodyDefault:
        'The Vendors tab lists every supplier with its code, country, rating, payment terms and status. Click New Vendor to add one with its own trading currency and terms, and use the status filter to focus on active, suspended, blacklisted or pending suppliers.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.supplier_catalogs.catalog.title',
      titleDefault: 'Build the priced catalog',
      bodyKey: 'guide.supplier_catalogs.catalog.body',
      bodyDefault:
        'The Catalog tab holds the SKUs you order, each with a unit of measure, manufacturer and reorder point. Add an item with New Item, then use Compare prices on any row to see every vendor quote side by side.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.supplier_catalogs.compare.title',
      titleDefault: 'Compare prices and buy',
      bodyKey: 'guide.supplier_catalogs.compare.body',
      bodyDefault:
        'Price comparison shows each vendor unit price, lead time, minimum order quantity and rating, and flags the cheapest when all quotes share one currency. Create PO hands the chosen vendor and line straight to Procurement with the details prefilled.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.supplier_catalogs.warehouses.title',
      titleDefault: 'Track warehouse stock',
      bodyKey: 'guide.supplier_catalogs.warehouses.body',
      bodyDefault:
        'The Warehouses tab registers storage locations and shows stock on hand, reserved quantities, average cost and last movement per item. Pick a warehouse from the selector to read its current balances.',
    },
  ],
  ctaKey: 'guide.supplier_catalogs.cta',
  ctaDefault: 'Register your first vendor',
};
