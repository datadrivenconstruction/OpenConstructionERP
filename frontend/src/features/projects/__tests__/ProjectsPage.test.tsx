// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { isProjectFilterActive, buildStatusFilterOptions } from '../ProjectsPage';
import { CURATED_PROJECT_STATUSES } from '../ProjectStatusBadge';

/**
 * Regression lock for #284: the filter toolbar (incl. the Active/Archived
 * switch) must stay mounted whenever a filter/search is active, even if the
 * filtered fetch returns an empty list. The page gates the toolbar on
 * `(projects.length > 0) || hasActiveFilter`, where `hasActiveFilter` is this
 * helper. Previously an empty Archived view (filter active, zero results)
 * collapsed the toolbar and stranded the user with no way back to Active.
 *
 * Testing the predicate directly keeps this lock fast and free of the page's
 * heavy map/query dependencies while still pinning the exact behaviour that
 * regressed.
 */
describe('isProjectFilterActive (#284 toolbar visibility)', () => {
  it('is false for the default view (no search, status=active, region=all)', () => {
    expect(isProjectFilterActive('', 'active', 'all')).toBe(false);
  });

  it('is true in the Archived view so the toolbar survives an empty result', () => {
    // This is the exact regression: archived view with zero archived
    // projects must still report an active filter so the toolbar (and its
    // Active/Archived switch) stays visible.
    expect(isProjectFilterActive('', 'archived', 'all')).toBe(true);
  });

  it('is true for the All filter, which brings deleted projects back into view', () => {
    expect(isProjectFilterActive('', 'all', 'all')).toBe(true);
  });

  it('is true when a search term is present', () => {
    expect(isProjectFilterActive('tower', 'active', 'all')).toBe(true);
  });

  it('is true when a region filter is set', () => {
    expect(isProjectFilterActive('', 'active', 'Bavaria')).toBe(true);
  });
});

/**
 * Item 3 (#284 follow-up): the status filter must offer ALL statuses, not
 * just All/Active/Archived. The option list is the curated recommended set
 * (which carries Active and Archived) UNION any distinct status actually
 * present on the fetched projects, mirroring the availableRegions pattern.
 * 'waiting' was removed from the curated set (item 4) and must not reappear
 * unless a project literally still carries it.
 */
describe('buildStatusFilterOptions (#284 status filter)', () => {
  it("leads with the 'all' sentinel then the full curated set", () => {
    const opts = buildStatusFilterOptions([]);
    expect(opts[0]).toBe('all');
    for (const s of CURATED_PROJECT_STATUSES) {
      expect(opts).toContain(s);
    }
  });

  it('always offers active and archived even with no projects', () => {
    const opts = buildStatusFilterOptions([]);
    expect(opts).toContain('active');
    expect(opts).toContain('archived');
  });

  it('no longer offers the removed "waiting" status by default', () => {
    expect(buildStatusFilterOptions([])).not.toContain('waiting');
  });

  it('unions a custom status present on a project', () => {
    const opts = buildStatusFilterOptions(['active', 'in_review', 'on_hold']);
    expect(opts).toContain('in_review');
    // Curated members are not duplicated when also present on a project.
    expect(opts.filter((s) => s === 'on_hold')).toHaveLength(1);
    expect(opts.filter((s) => s === 'active')).toHaveLength(1);
  });

  it('keeps a legacy "waiting" value selectable only if a project still has it', () => {
    expect(buildStatusFilterOptions(['waiting'])).toContain('waiting');
  });

  it('ignores empty / whitespace / nullish statuses', () => {
    const opts = buildStatusFilterOptions(['', '   ', null, undefined, 'shipped']);
    expect(opts).toContain('shipped');
    expect(opts).not.toContain('');
    expect(opts).not.toContain('   ');
    // No empty-string slot crept in.
    expect(opts.every((s) => s.trim().length > 0)).toBe(true);
  });

  it('produces a de-duplicated list (no repeated option values)', () => {
    const opts = buildStatusFilterOptions(['active', 'active', 'on_hold', 'on_hold']);
    expect(new Set(opts).size).toBe(opts.length);
  });
});
