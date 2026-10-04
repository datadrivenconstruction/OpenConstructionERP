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

function resolve<T extends { status: string; metadata?: Record<string, unknown> | null }>(
  query: { isPending: boolean; isError: boolean; data?: Page<T> },
  keys: AwardKeys,
  retired: ReadonlySet<string>,
): AwardLookup<T> {
  if (query.isError) return { state: 'unknown' };
  if (query.isPending || !query.data) return { state: 'loading' };
  const record = findAwardRecord(query.data.items, keys, retired);
  if (record) return { state: 'found', record };
  return isTruncated(query.data) ? { state: 'unknown' } : { state: 'absent' };
}

/**
 * Look up what an award drafted. `enabled` is the caller's "this package is
 * awarded"; before that there is nothing to look for and nothing is fetched.
 */
export function useAwardOutcome(projectId: string | null | undefined, keys: AwardKeys, enabled: boolean): AwardOutcome {
  const on = enabled && !!projectId;

  const contractsQ = useQuery({
    queryKey: ['award-outcome', 'contracts', projectId],
    queryFn: () => listContracts({ project_id: projectId as string, limit: CONTRACT_PAGE }),
    enabled: on,
    retry: false,
  });

  const ordersQ = useQuery({
    queryKey: ['award-outcome', 'orders', projectId],
    queryFn: () =>
      apiGet<Page<AwardOrderLite>>(
        `/v1/procurement/?project_id=${encodeURIComponent(projectId as string)}&limit=${ORDER_PAGE}`,
      ),
    enabled: on,
    retry: false,
  });

  if (!on) return { contract: { state: 'unknown' }, order: { state: 'unknown' } };
  return {
    contract: resolve(contractsQ, keys, RETIRED_AWARD_CONTRACT_STATUSES),
    order: resolve(ordersQ, keys, RETIRED_AWARD_ORDER_STATUSES),
  };
}
