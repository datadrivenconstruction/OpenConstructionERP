// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public surface of the Team Visibility feature.
 *
 * The default export is the page component, so the app router can lazy-load it
 * in one line: `lazy(() => import('@/features/teams'))`. The typed API client
 * is re-exported for any other module that needs to read a record's visibility
 * or offer a "restrict this to a team" control on its own screen.
 */

export { TeamsPage, default } from './TeamsPage';
export * from './api';
