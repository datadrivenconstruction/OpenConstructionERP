// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';

import { meFixture } from './__fixtures__/me';
import {
  closedLockForPath,
  lockIdForCatalogueRow,
  lockIdsForPath,
  lockedLockIds,
  matchesRoutePattern,
  normalizePath,
  panelAnchorFor,
  stripProjectPrefix,
} from './routeMatch';
import type { UnlockInfo } from './types';

function unlock(lock_id: string, state: 'open' | 'locked', kind: UnlockInfo['kind'] = 'module'): UnlockInfo {
  return { lock_id, kind, state, opened_by_task: 1, opened_at: null, seen: false, tiles: [] };
}

describe('normalizePath', () => {
  it('drops the query and the hash, lower-cases, and collapses slashes', () => {
    expect(normalizePath('/Contracts?tab=claims#x')).toBe('/contracts');
    expect(normalizePath('//variations//x/')).toBe('/variations/x');
    expect(normalizePath('/')).toBe('/');
    expect(normalizePath('variations')).toBe('/variations');
  });
});

describe('stripProjectPrefix', () => {
  it('strips /projects/:id before a module path', () => {
    expect(stripProjectPrefix('/projects/p1/variations')).toBe('/variations');
    expect(stripProjectPrefix('/projects/p1/contracts/claims/c9')).toBe('/contracts/claims/c9');
  });

  it('leaves the project list and a bare project page alone', () => {
    expect(stripProjectPrefix('/projects')).toBe('/projects');
    expect(stripProjectPrefix('/projects/p1')).toBe('/projects/p1');
  });
});

describe('matchesRoutePattern', () => {
  it('matches exactly and as a whole-segment prefix', () => {
    expect(matchesRoutePattern('/variations', '/variations')).toBe(true);
    expect(matchesRoutePattern('/variations/vr-1', '/variations')).toBe(true);
    expect(matchesRoutePattern('/variations-foo', '/variations')).toBe(false);
    expect(matchesRoutePattern('/variation', '/variations')).toBe(false);
  });

  it('treats the project-scoped form as the same module', () => {
    expect(matchesRoutePattern('/projects/p1/variations', '/variations')).toBe(true);
    expect(matchesRoutePattern('/variations', '/projects/:projectId/variations')).toBe(true);
  });

  it('matches :params against one segment only', () => {
    const claim = '/projects/:projectId/contracts/claims/:claimId';
    expect(matchesRoutePattern('/projects/p1/contracts/claims/c9', claim)).toBe(true);
    expect(matchesRoutePattern('/projects/p1/contracts/claims', claim)).toBe(false);
  });

  it('ignores the query string and case', () => {
    expect(matchesRoutePattern('/Bid-Management?x=1', '/bid-management')).toBe(true);
  });
});

describe('lockIdsForPath', () => {
  it('maps each gated module route to its lock', () => {
    expect(lockIdsForPath('/bid-management')).toEqual(['bid_management']);
    expect(lockIdsForPath('/projects/p1/bid-management/pkg-1')).toEqual(['bid_management']);
    expect(lockIdsForPath('/variations')).toEqual(['variations']);
    expect(lockIdsForPath('/contracts')).toEqual(['contracts']);
  });

  it('returns the most specific lock first when two match', () => {
    expect(lockIdsForPath('/projects/p1/contracts/claims/c9')).toEqual(['contracts.progress_claims', 'contracts']);
  });

  it('never gates /markups, which is the PDF markups module', () => {
    expect(lockIdsForPath('/markups')).toEqual([]);
    expect(lockIdsForPath('/projects/p1/markups')).toEqual([]);
  });

  it('never gates the public bidder link or other open routes', () => {
    expect(lockIdsForPath('/tendering/bid/abc')).toEqual([]);
    expect(lockIdsForPath('/boq/7a4c')).toEqual([]);
    expect(lockIdsForPath('/projects')).toEqual([]);
    expect(lockIdsForPath('/projects/p1')).toEqual([]);
    expect(lockIdsForPath('/academy')).toEqual([]);
    expect(lockIdsForPath('/')).toEqual([]);
  });

  it('never gates a tab through the query string', () => {
    expect(lockIdsForPath('/contracts?tab=claims')).toEqual(['contracts']);
    expect(lockIdsForPath('/contracts?tab=claims')).not.toContain('contracts.progress_claims');
  });
});

describe('closedLockForPath', () => {
  it('is null without an enrolment or with nothing locked', () => {
    expect(closedLockForPath('/variations', null)).toBeNull();
    expect(closedLockForPath('/variations', { unlocks: [unlock('variations', 'open')] })).toBeNull();
  });

  it('returns the matching lock that /me holds closed', () => {
    expect(closedLockForPath('/projects/p1/variations', meFixture)).toBe('variations');
    expect(closedLockForPath('/bid-management', meFixture)).toBe('bid_management');
  });

  it('a lock the course does not list is open (FR locks contracts, not the claims tab)', () => {
    const fr = { unlocks: [unlock('contracts', 'locked')] };
    expect(closedLockForPath('/projects/p1/contracts/claims/c9', fr)).toBe('contracts');
    const uk = { unlocks: [unlock('contracts.progress_claims', 'locked', 'tab')] };
    expect(closedLockForPath('/projects/p1/contracts/claims/c9', uk)).toBe('contracts.progress_claims');
    expect(closedLockForPath('/contracts', uk)).toBeNull();
  });

  it('a route outside the course is never locked', () => {
    expect(closedLockForPath('/finance', meFixture)).toBeNull();
    expect(closedLockForPath('/tendering', meFixture)).toBeNull();
    expect(closedLockForPath('/changeorders', meFixture)).toBeNull();
  });
});

describe('lockedLockIds', () => {
  it('collects only locked unlocks, badges included', () => {
    const ids = lockedLockIds(meFixture);
    expect(ids.has('variations')).toBe(true);
    expect(ids.has('boq.markups_panel')).toBe(false);
    expect(ids.has('badge:fx-quillmere-1')).toBe(true);
  });
});

describe('catalogue rows and panels', () => {
  it('finds the lock behind a navCatalog row', () => {
    expect(lockIdForCatalogueRow('/bid-management')).toBe('bid_management');
    expect(lockIdForCatalogueRow('/variations/')).toBe('variations');
    expect(lockIdForCatalogueRow('/markups')).toBeNull();
    expect(lockIdForCatalogueRow('/finance')).toBeNull();
  });

  it('names the anchor of the markups panel', () => {
    expect(panelAnchorFor('boq.markups_panel')).toBe('boq-markups-panel');
    expect(panelAnchorFor('variations')).toBeNull();
    expect(panelAnchorFor('badge:x')).toBeNull();
  });
});
