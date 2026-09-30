// A stored active project that the server no longer lists must not leave the
// user on 404s, and must not strand them on an empty picker when they have
// other projects.

import { describe, it, expect } from 'vitest';
import { resolveStaleProject } from './staleProject';

const A = { id: 'p-a', name: 'Alpha' };
const B = { id: 'p-b', name: 'Beta' };

describe('resolveStaleProject', () => {
  it('keeps a project that is still listed', () => {
    expect(resolveStaleProject([A, B], 'p-b')).toEqual({ kind: 'keep' });
  });

  it('switches a vanished project to the first listed one', () => {
    expect(resolveStaleProject([A, B], 'p-gone')).toEqual({ kind: 'switch', id: 'p-a', name: 'Alpha' });
  });

  it('clears when the user has no projects left', () => {
    expect(resolveStaleProject([], 'p-gone')).toEqual({ kind: 'clear' });
  });

  it('skips entries without an id', () => {
    expect(resolveStaleProject([{ id: '', name: 'x' }, B], 'p-gone')).toEqual({
      kind: 'switch',
      id: 'p-b',
      name: 'Beta',
    });
  });
});
