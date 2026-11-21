import { describe, expect, it } from 'vitest';
import { isFloatingChatLiftedOn } from '../useFloatingChat';

describe('floating assistant button over a plan status bar', () => {
  it('rises on the survey plan editor, where the status bar runs along the bottom', () => {
    expect(isFloatingChatLiftedOn('/survey/plan')).toBe(true);
    expect(isFloatingChatLiftedOn('/survey/plan/anything')).toBe(true);
  });

  it('stays in its corner elsewhere', () => {
    expect(isFloatingChatLiftedOn('/survey')).toBe(false);
    expect(isFloatingChatLiftedOn('/survey/planning')).toBe(false);
    expect(isFloatingChatLiftedOn('/boq')).toBe(false);
  });
});
