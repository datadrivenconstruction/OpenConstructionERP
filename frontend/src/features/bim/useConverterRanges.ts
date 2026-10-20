import { useQuery } from '@tanstack/react-query';
import { fetchBIMConverters } from './api';

/**
 * Source-format ranges of the given converters, joined for one line of text
 * ("Revit 2019-2027 · IFC2x3, IFC4"). The ranges are declared once on the
 * server (`converter_source.PACKAGES`); this only reads them through the same
 * `['bim-converters']` query the converter panel uses, so no screen keeps its
 * own copy. Empty while the list loads or when the server does not answer.
 */
export function useConverterRanges(ids: readonly string[]): string {
  const { data } = useQuery({
    queryKey: ['bim-converters'],
    queryFn: () => fetchBIMConverters(),
    staleTime: 60_000,
  });
  const byId = new Map((data?.converters ?? []).map((c) => [c.id, c.format_range]));
  return ids
    .map((id) => byId.get(id))
    .filter((range): range is string => Boolean(range))
    .join(' · ');
}
