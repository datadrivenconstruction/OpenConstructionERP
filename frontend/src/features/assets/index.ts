// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Asset Operations feature.
 *
 * Operational-phase intelligence on top of the BIM-sourced Asset Register:
 * a portfolio KPI strip, BIM asset discovery, warranty-expiry alerting, and
 * per-asset maintenance/service logging. All of it reads the computed
 * ``/api/v1/assets`` endpoints and writes through the existing BIM Hub
 * asset-info path, so it needs no schema of its own.
 *
 * These are self-contained, drop-in pieces. The Asset Register page can
 * mount ``AssetOperationsToolbar`` above its list and ``AssetPortfolioStrip``
 * for the KPI roll-up; ``ServiceLogPanel`` slots into the asset detail
 * drawer.
 */
export { AssetPortfolioStrip } from './AssetPortfolioStrip';
export { DiscoverAssetsModal } from './DiscoverAssetsModal';
export { WarrantyAlertsButton } from './WarrantyAlertsButton';
export { ServiceLogPanel } from './ServiceLogPanel';
export { AssetOperationsToolbar } from './AssetOperationsToolbar';
export * from './api';
