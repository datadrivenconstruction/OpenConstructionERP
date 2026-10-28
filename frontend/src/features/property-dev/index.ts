// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
export { PropertyDevPage } from './PropertyDevPage';
export { InventoryMapPage } from './InventoryMapPage';
export { TaxQuotePanel } from './TaxQuotePanel';
// Only the routed wrapper leaves this barrel. The props-taking panel behind it
// stays module-internal: exporting both would put an unrouted, unembedded page
// in the barrel, and the gate over this file would then need an exemption
// saying something embeds it when nothing does.
export { CompliancePageRoute } from './CompliancePage';
export { HouseTypeSettingsPage } from './HouseTypeSettingsPage';
export { ValidationRulesSettingsPage } from './ValidationRulesSettingsPage';
export { DocumentTemplatesSettingsPage } from './DocumentTemplatesSettingsPage';
export { PricingEnginePage } from './PricingEnginePage';
export { BulkOperationsPage } from './BulkOperationsPage';
