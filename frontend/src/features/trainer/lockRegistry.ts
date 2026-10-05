// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The lock ids a course may name in `tasks[].opens`, mirrored from
// backend/app/modules/trainer/locks.py. Both sides hold the same list, and a
// parity test on each side reads the other file: lockRegistry.test.ts reads
// locks.py, and the backend's test_trainer_contract_parity.py reads this file.
// Add or remove a lock in both places in one change.
//
// Data only. No labels live here: the label a learner sees is the course's
// own `opens_label`, in the course language, so this file adds no i18n key.
//
// Two traps the ids invite:
// - `boq.markups_panel` is the BOQ markups panel. It never locks `/markups`,
//   which is the PDF drawing markups module.
// - `contracts.progress_claims` is a tab: the claims tab is gated inside
//   ContractsPage, never by a URL lock on `?tab=claims`.

import type { LockKind } from './types';

export interface LockRegistryEntry {
  // The value a course writes in `tasks[].opens`.
  lockId: string;
  kind: LockKind;
  // Backend manifest name whose screens the lock covers.
  module: string;
  // App.tsx route paths that show the locked page while the lock is closed.
  routes: readonly string[];
  // The navCatalog row (`to`) this lock hides from the normal menu, if any.
  catalogueRow: string | null;
  // DOM id of the panel a `panel` or `tab` lock replaces with a locked card.
  panelAnchor: string | null;
}

export const BADGE_PREFIX = 'badge:';

export const LOCK_REGISTRY: readonly LockRegistryEntry[] = [
  {
    lockId: 'boq.markups_panel',
    kind: 'panel',
    module: 'oe_boq',
    routes: [],
    catalogueRow: null,
    panelAnchor: 'boq-markups-panel',
  },
  {
    lockId: 'bid_management',
    kind: 'module',
    module: 'oe_bid_management',
    routes: ['/bid-management', '/projects/:projectId/bid-management'],
    catalogueRow: '/bid-management',
    panelAnchor: null,
  },
  {
    lockId: 'contracts.progress_claims',
    kind: 'tab',
    module: 'oe_contracts',
    routes: ['/projects/:projectId/contracts/claims/:claimId'],
    catalogueRow: null,
    panelAnchor: null,
  },
  {
    lockId: 'contracts',
    kind: 'module',
    module: 'oe_contracts',
    routes: ['/contracts', '/projects/:projectId/contracts', '/projects/:projectId/contracts/claims/:claimId'],
    catalogueRow: '/contracts',
    panelAnchor: null,
  },
  {
    lockId: 'variations',
    kind: 'module',
    module: 'oe_variations',
    routes: ['/variations', '/projects/:projectId/variations'],
    catalogueRow: '/variations',
    panelAnchor: null,
  },
];

const BY_ID: ReadonlyMap<string, LockRegistryEntry> = new Map(LOCK_REGISTRY.map((entry) => [entry.lockId, entry]));

export function isBadgeLockId(value: string): boolean {
  return value.startsWith(BADGE_PREFIX) && value.length > BADGE_PREFIX.length;
}

export function isKnownLockId(value: string): boolean {
  return BY_ID.has(value) || isBadgeLockId(value);
}

export function lockKind(value: string): LockKind | null {
  if (isBadgeLockId(value)) return 'badge';
  return BY_ID.get(value)?.kind ?? null;
}

export function getLock(value: string): LockRegistryEntry | null {
  return BY_ID.get(value) ?? null;
}
