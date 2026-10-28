// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Construction Control's tab ids, as ?tab= carries them
 * (/projects/:projectId/construction-control?tab=handover). Kept apart from
 * the page so a case step or a guide test can check a link names a real tab
 * without loading the page.
 */

export type ConstructionControlTab = 'inspections' | 'materials' | 'asbuilt' | 'gates' | 'handover';

export const CONSTRUCTION_CONTROL_TABS: readonly ConstructionControlTab[] = [
  'inspections',
  'materials',
  'asbuilt',
  'gates',
  'handover',
];

/** The tab shown for a missing or unknown ?tab= value. */
export const DEFAULT_CONSTRUCTION_CONTROL_TAB: ConstructionControlTab = 'inspections';

export function isConstructionControlTab(value: string | null): value is ConstructionControlTab {
  return value !== null && (CONSTRUCTION_CONTROL_TABS as readonly string[]).includes(value);
}
