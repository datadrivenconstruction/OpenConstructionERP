// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The purchase order each awarded RFQ drafted, for the whole Awards tab at once.
 *
 * Awarding an RFQ drafts a purchase order in a subscriber that runs after the
 * award commits (`backend/app/modules/procurement/rfq_award.py`). The RFQ does
 * not store the order's id; the order carries the RFQ's id in its metadata, so
 * the way back is a scan of the project's orders, as `useAwardOutcome` does for
 * the tender and bid-package awards. That hook asks per package and also reads
 * contracts, which an RFQ award does not draft; the Awards tab lists every
 * awarded RFQ of the project, so it reads the order register once and answers
 * each card from that one page.
 *
 * Each answer is one of the shared `AwardLookup` states, with the same
 * meaning: `found`, `absent` (the whole register was read and no order carries
 * the stamp), `unknown` (the read failed or the register is longer than one
 * page) and `loading`.
 *
 * Re-reading: the draft lands a moment after the award, so an RFQ awarded on
 * this screen is looked for a few more times. `awaitDraftFor` names that RFQ
 * and is part of the cache key, so each new award starts its own re-read
 * budget instead of inheriting one an earlier award used up. While that budget
 * lasts the awaited RFQ answers `loading` rather than `absent`, so the card
 * says the order is on its way instead of offering to raise one by hand.
 * Without `awaitDraftFor` the register is read once.
 */

import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, isTruncated, type Page } from '@/shared/lib/api';
import { findRfqAwardOrder } from '@/shared/lib/awardChainLinks';
import type { AwardLookup, AwardOrderLite } from '@/shared/hooks/useAwardOutcome';

/** The server's ceiling on one page of the order register. */
const ORDER_PAGE = 100;
/** Same budget as `useAwardOutcome`: a few re-reads a few seconds apart. */
export const DRAFT_POLL_MS = 3000;
export const DRAFT_POLL_READS = 5;

export type RfqOrderLookup = (rfqId: string) => AwardLookup<AwardOrderLite>;

export function useRfqAwardOrders(
  projectId: string | null | undefined,
  enabled: boolean,
  awaitDraftFor: string | null,
): RfqOrderLookup {
  const on = enabled && !!projectId;
  const queryClient = useQueryClient();
  const queryKey = ['rfq-award-orders', projectId, awaitDraftFor ?? ''] as const;

  const query = useQuery({
    queryKey,
    queryFn: () =>
      apiGet<Page<AwardOrderLite>>(
        `/v1/procurement/?project_id=${encodeURIComponent(projectId as string)}&limit=${ORDER_PAGE}`,
      ),
    enabled: on,
    retry: false,
    // A register read for another reason must not stand in for this one.
    staleTime: 0,
    refetchInterval: (q) => {
      const page = q.state.data;
      if (!awaitDraftFor || !page || !Array.isArray(page.items) || isTruncated(page)) return false;
      if (findRfqAwardOrder(page.items, awaitDraftFor)) return false;
      return q.state.dataUpdateCount < DRAFT_POLL_READS ? DRAFT_POLL_MS : false;
    },
  });

  // `isFetching` is read so each re-read re-renders the caller even when the
  // page it returns is unchanged; the read count lives on the cache entry.
  const { isError, isPending, isFetching, data } = query;
  const reads = queryClient.getQueryState(queryKey)?.dataUpdateCount ?? 0;
  const awaiting = !!awaitDraftFor && (isFetching || reads < DRAFT_POLL_READS);
  return useCallback<RfqOrderLookup>(
    (rfqId) => {
      if (!on || isError) return { state: 'unknown' };
      if (isPending || !data) return { state: 'loading' };
      // A body that is not a page is not evidence of anything.
      if (!Array.isArray(data.items)) return { state: 'unknown' };
      const record = findRfqAwardOrder(data.items, rfqId);
      if (record) return { state: 'found', record };
      if (isTruncated(data)) return { state: 'unknown' };
      return awaiting && rfqId === awaitDraftFor ? { state: 'loading' } : { state: 'absent' };
    },
    [on, isError, isPending, data, awaiting, awaitDraftFor],
  );
}
