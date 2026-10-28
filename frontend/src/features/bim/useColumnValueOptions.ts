// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Distinct values of one model property, most common first, paged.
 *
 * Feeds the value dropdown of the property search panel and of the quantity
 * rule editor, so both offer the same values with the same counts. Best
 * effort: a model without a property table, or a failed fetch, leaves the
 * list empty and the value field stays a plain text input.
 */

import { useCallback, useEffect, useState } from 'react';
import { fetchBIMDataframeColumnValues, type BIMDataframeValueCount } from './api';

export const VALUE_OPTIONS_LIMIT = 200;

export interface ColumnValueOptions {
  items: BIMDataframeValueCount[];
  total: number;
  loading: boolean;
  /** Fetch the next page and append it. */
  loadMore: () => void;
}

export function useColumnValueOptions(
  modelId: string | null | undefined,
  column: string,
  enabled: boolean,
): ColumnValueOptions {
  const [items, setItems] = useState<BIMDataframeValueCount[]>([]);
  const [offset, setOffset] = useState(0);
  const [request, setRequest] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOffset(0);
    setItems([]);
    setTotal(0);
  }, [enabled, column, modelId]);

  useEffect(() => {
    if (!enabled || !column || !modelId) {
      setItems([]);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    fetchBIMDataframeColumnValues(modelId, column, VALUE_OPTIONS_LIMIT, ctrl.signal, offset)
      .then((page) => {
        if (!cancelled) {
          setItems((previous) => (offset === 0 ? page.items : [...previous, ...page.items]));
          setTotal(page.total);
        }
      })
      .catch(() => {
        if (!cancelled && offset === 0) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [enabled, column, modelId, offset, request]);

  const loadMore = useCallback(() => {
    setOffset(items.length);
    setRequest((n) => n + 1);
  }, [items.length]);

  return { items, total, loading, loadMore };
}
