import { describe, expect, it } from 'vitest';
import { projectFilterOptions } from '../projectFilterOptions';

describe('project filter on the estimates list', () => {
  it('offers every project, including two with the same name', () => {
    const options = projectFilterOptions([
      { id: 'aaaaaaaa-1111', name: 'Tower A' },
      { id: 'bbbbbbbb-2222', name: 'Tower A' },
      { id: 'cccccccc-3333', name: 'Depot' },
    ]);
    expect(options.map((o) => o.id)).toEqual(['aaaaaaaa-1111', 'bbbbbbbb-2222', 'cccccccc-3333']);
  });

  it('tells same-named projects apart and leaves unique names as they are', () => {
    const options = projectFilterOptions([
      { id: 'aaaaaaaa-1111', name: 'Tower A' },
      { id: 'bbbbbbbb-2222', name: 'Tower A' },
      { id: 'cccccccc-3333', name: 'Depot' },
    ]);
    expect(options[0]!.label).not.toBe(options[1]!.label);
    expect(options[2]!.label).toBe('Depot');
  });

  it('lists a project once when a page repeated it', () => {
    const options = projectFilterOptions([
      { id: 'aaaaaaaa-1111', name: 'Tower A' },
      { id: 'aaaaaaaa-1111', name: 'Tower A' },
    ]);
    expect(options).toHaveLength(1);
    expect(options[0]!.label).toBe('Tower A');
  });
});
