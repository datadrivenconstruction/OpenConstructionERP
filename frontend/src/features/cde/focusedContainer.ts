// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The register rows to draw when a link names one container.
 *
 * `?container=<id>` is where the "published" notification sends its reader.
 * The register reads one page of containers (the list endpoint answers 50 by
 * default) and a drawing register is usually longer than that, so the named
 * container is often not among the rows the list returned. Matching it only
 * against those rows left the link doing nothing for every container past the
 * first page, with no word to the reader. The page now fetches the named
 * container on its own when the list does not hold it, and this puts it on
 * top of the rows.
 */
import type { CDEContainer, CDEState } from './api';

export interface FocusScope {
  /** Project the register shows. A container of another project is never pinned. */
  projectId: string;
  /** Active state tab, `''` for all. A container in another state is not pinned under it. */
  stateFilter: CDEState | '';
  /** Free-text search. While someone is searching, the rows are theirs. */
  searchQuery: string;
}

/** Pin `focused` above `rows` when the list does not already hold it.
 *
 *  Leaves `rows` as they are when nothing is focused, when the container is
 *  already listed, when it belongs to another project, when the active state
 *  tab would not show it, or while a search is typed. */
export function withFocusedContainer(
  rows: CDEContainer[],
  focused: CDEContainer | null | undefined,
  scope: FocusScope,
): CDEContainer[] {
  if (!focused) return rows;
  if (rows.some((c) => c.id === focused.id)) return rows;
  if (focused.project_id !== scope.projectId) return rows;
  if (scope.stateFilter && (focused.cde_state ?? 'wip') !== scope.stateFilter) return rows;
  if (scope.searchQuery.trim()) return rows;
  return [focused, ...rows];
}
