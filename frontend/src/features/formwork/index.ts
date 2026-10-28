// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public surface of the Formwork feature.
 *
 * The default export is the page component, so the app router can lazy-load it
 * in one line: `lazy(() => import('@/features/formwork'))`. The typed API
 * client is re-exported for any other consumer (a BOQ position that wants to
 * show its formwork rate, a report that wants the project rollup).
 */

export { FormworkPage, default } from './FormworkPage';
export * from './api';
