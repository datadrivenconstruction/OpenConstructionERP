// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public surface of the Design Options feature.
 *
 * The default export is the page component, so the app router can lazy-load it
 * in one line: `lazy(() => import('@/features/design-options'))`. Named exports
 * cover the comparison table and the typed API client for any other consumer.
 */

export { DesignOptionsPage, default } from './DesignOptionsPage';
export { DesignOptionComparisonTable } from './DesignOptionComparisonTable';
export type { DesignOptionComparisonTableProps } from './DesignOptionComparisonTable';
export * from './api';
