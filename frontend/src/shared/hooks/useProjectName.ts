// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/**
 * The name of the project a page is open on, for the root of its breadcrumb.
 * The header keeps the project context in step with the address, so the name is
 * the store's when its id is this page's. Null while it is not known, and the
 * page then falls back to its generic "Project" label.
 */
export function useProjectName(projectId: string | undefined): string | null {
  return useProjectContextStore((s) => (projectId && s.activeProjectId === projectId ? s.activeProjectName || null : null));
}
