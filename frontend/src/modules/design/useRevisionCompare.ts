// Design module (ERP side of the design editor link).
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchBIMElements } from '@/features/bim/api';
import { compareRevisions, type CompareElement, type Comparison, type RevisionView } from './data/revisions';

const PAGE = 20000;

/**
 * Every element of a model, page by page. A model that cannot be read completely is an error: comparing
 * a partial list would report invented additions and removals.
 */
export async function fetchAllElements(modelId: string): Promise<CompareElement[]> {
  const all: CompareElement[] = [];
  for (;;) {
    const page = await fetchBIMElements(modelId, { skeleton: true, limit: PAGE, offset: all.length });
    const items = page.items as unknown as CompareElement[];
    all.push(...items);
    if (all.length >= page.total) break;
    if (items.length === 0 || items.length < PAGE) throw new Error('design: model element list is incomplete');
  }
  return all;
}

/** Element-level comparison of two revisions' models, or null while either side loads or when one is missing. */
export function useRevisionCompare(
  base: RevisionView | null,
  head: RevisionView | null,
): { cmp: Comparison | null; failed: boolean } {
  const query = (rev: RevisionView | null) => ({
    queryKey: ['design-compare', rev?.bim_model_id],
    queryFn: () => fetchAllElements(rev!.bim_model_id!),
    enabled: !!rev?.bim_model_id,
    // An incomplete model is a result to show, not something to retry silently.
    retry: false,
  });
  const before = useQuery(query(base));
  const after = useQuery(query(head));
  const cmp = useMemo(
    () => (before.data && after.data
      ? compareRevisions(before.data, after.data)
      : null),
    [before.data, after.data],
  );
  return { cmp, failed: before.isError || after.isError };
}
