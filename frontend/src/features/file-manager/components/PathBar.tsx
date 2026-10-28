// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** PathBar — intentionally hidden.
 *
 * Earlier revisions surfaced the absolute filesystem paths used by the
 * backend (DB / uploads / photos / BIM / DWG) at the top of /files so
 * desktop self-hosters could locate their data on disk.  On hosted
 * deployments that became a privacy/clutter problem — every viewer saw
 * the server's directory layout — so the bar is a no-op.  Users who need
 * the underlying paths can find them in /settings → System.
 */
import type { StorageLocations } from '../types';

interface PathBarProps {
  locations: StorageLocations | undefined;
  isLoading: boolean;
  selectedKind?: string | null;
}

export function PathBar(_props: PathBarProps) {
  return null;
}
