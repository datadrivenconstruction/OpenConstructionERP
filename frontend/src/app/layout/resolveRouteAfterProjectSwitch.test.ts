import { describe, it, expect } from 'vitest';
import { resolveRouteAfterProjectSwitch } from './Header';

const U = '3f2b8c1e-5a4d-4e6f-9a1b-0c2d3e4f5a6b';

describe('resolveRouteAfterProjectSwitch record segments', () => {
  it('drops a model id under /projects/:id/bim', () => {
    expect(resolveRouteAfterProjectSwitch(`/projects/A/bim/${U}`, 'B')).toBe('/projects/B/bim');
  });
  it('keeps non-record suffixes', () => {
    expect(resolveRouteAfterProjectSwitch('/projects/A/finance', 'B')).toBe('/projects/B/finance');
  });
  it('lands on the list for uuid detail routes outside /projects', () => {
    expect(resolveRouteAfterProjectSwitch(`/schedule/${U}`, 'B')).toBe('/schedule');
    expect(resolveRouteAfterProjectSwitch(`/accommodation/${U}`, 'B')).toBe('/accommodation');
  });
  it('leaves list routes alone', () => {
    expect(resolveRouteAfterProjectSwitch('/schedule', 'B')).toBeNull();
  });
});
