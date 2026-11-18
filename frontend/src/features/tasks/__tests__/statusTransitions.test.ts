import { describe, expect, it } from 'vitest';

import { canMoveStatus, statusOptionsFor } from '../statusTransitions';

describe('task status moves', () => {
  it('lets a draft go to open, in progress and completed from the menu and the board', () => {
    expect(statusOptionsFor('draft')).toEqual(['draft', 'open', 'in_progress', 'completed']);
    expect(canMoveStatus('draft', 'open')).toBe(true);
    expect(canMoveStatus('draft', 'in_progress')).toBe(true);
    expect(canMoveStatus('draft', 'completed')).toBe(true);
  });

  it('still refuses work in progress going back to draft', () => {
    expect(canMoveStatus('in_progress', 'draft')).toBe(false);
    expect(canMoveStatus('completed', 'draft')).toBe(false);
  });

  it('never blocks a move that touches a custom status', () => {
    expect(canMoveStatus('draft', 'waiting_for_client')).toBe(true);
    expect(statusOptionsFor('waiting_for_client')).toEqual(['draft', 'open', 'in_progress', 'completed']);
  });
});
