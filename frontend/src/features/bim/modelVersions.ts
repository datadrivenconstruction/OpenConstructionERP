/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Model versions: an upload can declare itself a new version of a model the
 * project already holds (``parent_model_id``), so the quantity rules that
 * priced the earlier version can be re-applied to it through the BOQ change
 * review.
 */
import { compareNames } from '@/shared/lib/collator';
import type { BIMModelData } from '@/shared/ui/BIMViewer';

/** Import states after which a model has its elements. The server's
 *  ``USABLE_MODEL_STATUSES`` in bim_hub/service.py is the same set. */
const USABLE_STATUSES = new Set(['ready', 'complete', 'completed', 'done', 'active']);

export function isUsableModelStatus(status: string | null | undefined): boolean {
  return USABLE_STATUSES.has((status ?? '').trim().toLowerCase());
}

/**
 * Models a new upload can be a version of: imported, and not already
 * replaced by a finished newer version. The server refuses the others, so
 * the picker does not offer them. A newer version that failed or is still
 * converting does not count, so a failed upload can be retried.
 */
export function versionParentOptions(
  models: readonly BIMModelData[],
  compare: (a: string, b: string) => number = compareNames,
): BIMModelData[] {
  const replaced = new Set(
    models
      .filter((m) => m.parent_model_id && isUsableModelStatus(m.status))
      .map((m) => m.parent_model_id as string),
  );
  return models
    .filter((m) => isUsableModelStatus(m.status) && !replaced.has(m.id))
    .sort((a, b) => compare(a.name, b.name));
}
