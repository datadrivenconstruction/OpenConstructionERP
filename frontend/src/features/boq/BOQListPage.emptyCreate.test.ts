import { describe, it, expect } from 'vitest';
import { emptyStateCreateTarget } from './BOQListPage';

describe('emptyStateCreateTarget', () => {
  it('opens the create dialog when projects exist', () => {
    expect(emptyStateCreateTarget(3)).toBe('modal');
    expect(emptyStateCreateTarget(1)).toBe('modal');
  });

  it('goes to project creation only when there is no project', () => {
    expect(emptyStateCreateTarget(0)).toBe('project');
  });

  it('opens the dialog while the project list is loading', () => {
    expect(emptyStateCreateTarget(undefined)).toBe('modal');
  });
});
