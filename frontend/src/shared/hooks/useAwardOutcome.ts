// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The contract and purchase order an award drafted, found by the stamp the
 * award left on them.
 *
 * Awarding a tender package or a bid package drafts a contract and a purchase
 * order in subscribers that run after the award commits. Neither package
 * stores the id of what was drafted: the drafts carry the package id in their
 * metadata instead, which is how the two award paths find each other's draft
 * and stay idempotent. So the way back from an award to its contract is the
 * same scan the server makes, over the project's contracts and orders, newest
 * first.
 *
 * Each half reports one of three answers, and the caller draws them
 * differently:
 *
 * - `found`: the record; link to it by name.
 * - `absent`: the whole register was read and nothing carries the stamp; the
 *   draft may still be on its way (the subscriber is detached) or was never
 *   made (a module is not installed).
 * - `unknown`: the read failed, or the register is longer than one page and
 *   the stamp was not on it. Not an absence, so nothing is claimed.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet, isTruncated, type Page } from '@/shared/lib/api';
import { listContracts, type ContractItem } from '@/features/contracts/api';
import {
  findAwardRecord,
  RETIRED_AWARD_CONTRACT_STATUSES,
  RETIRED_AWARD_ORDER_STATUSES,
  type AwardKeys,
} from '@/shared/lib/awardChainLinks';

/** The slice of a purchase order this lookup needs (backend `POResponse`). */
export interface AwardOrderLite {
  id: string;
  po_number: string;
  status: string;
  metadata?: Record<string, unknown> | null;
}

export type AwardLookup<T> =
  | { state: 'found'; record: T }
  | { state: 'absent' }
  | { state: 'unknown' }
  | { state: 'loading' };

export interface AwardOutcome {
  contract: AwardLookup<ContractItem>;
  order: AwardLookup<AwardOrderLite>;
}

/** The server's ceiling on one page of each register. */
const CONTRACT_PAGE = 200;
const ORDER_PAGE = 100;

/**
 * How long to keep looking for a draft that is not there yet. The award
 * subscribers run detached after the award commits, so the first read right
 * after "Award" usually lands before the draft does. A few re-reads a few
 * seconds apart cover that, and then the lookup stops: a draft that has not
 * appeared by then was not made (a module is not installed), and polling a
 * register forever on an open screen is not free.
 */
const DRAFT_POLL_MS = 3000;
const DRAFT_POLL_READS = 5;

type StampedRow = { status: string; metadata?: Record<string, unknown> | null };

/** Re-read while the whole register was read and the stamp is not on it yet. */
function pollWhileAbsent<T extends StampedRow>(
  page: Page<T> | undefined,
  reads: number,
  keys: AwardKeys,
  retired: ReadonlySet<string>,
): number | false {
  if (!page || !Array.isArray(page.items) || isTruncated(page)) return false;
  if (findAwardRecord(page.items, keys, retired)) return false;
  return reads < DRAFT_POLL_READS ? DRAFT_POLL_MS : false;
}

function resolve<T extends StampedRow>(
  query: { isPending: boolean; isError: boolean; data: Page<T> | undefined },
  keys: AwardKeys,
  retired: ReadonlySet<string>,
): AwardLookup<T> {
  if (query.isError) return { state: 'unknown' };
  if (query.isPending || !query.data) return { state: 'loading' };
  // A body that is not a page (a proxy error page, an older server answering
  // with a bare list) is not evidence of anything, so it reads as unknown
  // rather than throwing inside the render that asked.
  if (!Array.isArray(query.data.items)) return { state: 'unknown' };
  const record = findAwardRecord(query.data.items, keys, retired);
  if (record) return { state: 'found', record };
  return isTruncated(query.data) ? { state: 'unknown' } : { state: 'absent' };
}

/**
 * The award a lookup belongs to, as part of its cache key. The re-read budget
 * is counted on the cache entry (`dataUpdateCount`), so an entry shared by
 * every award of a project let earlier awards, and the other screen that asks
 * the same question, spend the budget of the next one: it was enabled with
 * the counter already at the limit and never re-read. One entry per award
 * keeps each count to its own award.
 */
function awardScope(keys: AwardKeys): string {
  const bids = (keys.bid_package_ids ?? []).filter((id): id is string => Boolean(id));
  return [keys.tender_package_id || '', ...[...new Set(bids)].sort()].join('|');
}

export interface AwardOutcomeOptions {
  /**
   * Keep re-reading for a while when the draft is not there yet (default).
   * Off for a package whose award, if it had one, is long settled, such as a
   * tender package closed for archival: one read answers it, and a package
   * closed without an award would otherwise poll for a draft that never comes.
   */
  awaitDraft?: boolean;
}

/**
 * Look up what an award drafted. `enabled` is the caller's "this package is
 * awarded"; before that there is nothing to look for and nothing is fetched.
 */
export function useAwardOutcome(
  projectId: string | null | undefined,
  keys: AwardKeys,
  enabled: boolean,
  options: AwardOutcomeOptions = {},
): AwardOutcome {
  const on = enabled && !!projectId;
  const awaitDraft = options.awaitDraft ?? true;
  const scope = awardScope(keys);

  const contractsQ = useQuery({
    queryKey: ['award-outcome', 'contracts', projectId, scope],
    queryFn: () => listContracts({ project_id: projectId as string, limit: CONTRACT_PAGE }),
    enabled: on,
    retry: false,
    // The app-wide two minutes of freshness would let a register read for
    // another reason stand in for the read this award needs, so turning the
    // lookup on always reads.
    staleTime: 0,
    refetchInterval: (q) =>
      awaitDraft && pollWhileAbsent(q.state.data, q.state.dataUpdateCount, keys, RETIRED_AWARD_CONTRACT_STATUSES),
  });

  const ordersQ = useQuery({
    queryKey: ['award-outcome', 'orders', projectId, scope],
    queryFn: () =>
      apiGet<Page<AwardOrderLite>>(
        `/v1/procurement/?project_id=${encodeURIComponent(projectId as string)}&limit=${ORDER_PAGE}`,
      ),
    enabled: on,
    retry: false,
    staleTime: 0,
    refetchInterval: (q) =>
      awaitDraft && pollWhileAbsent(q.state.data, q.state.dataUpdateCount, keys, RETIRED_AWARD_ORDER_STATUSES),
  });

  if (!on) return { contract: { state: 'unknown' }, order: { state: 'unknown' } };
  return {
    contract: resolve(contractsQ, keys, RETIRED_AWARD_CONTRACT_STATUSES),
    order: resolve(ordersQ, keys, RETIRED_AWARD_ORDER_STATUSES),
  };
}
