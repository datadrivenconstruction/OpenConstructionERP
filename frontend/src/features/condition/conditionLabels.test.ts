import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { actionTypeLabel, levelLabel, levelOf } from './conditionLabels';

const t = ((key: string) => key) as unknown as TFunction;

describe('condition labels', () => {
  it('translates the shipped scale and shows other scales as data', () => {
    expect(levelLabel(t, 'default_6', { level: 6, label: 'Very poor' })).toBe('condition.level_default_6_6');
    expect(levelLabel(t, 'pack_scale', { level: 2, label: 'Note 2' })).toBe('Note 2');
  });

  it('labels action types and finds levels', () => {
    expect(actionTypeLabel(t, 'repair')).toBe('condition.action_repair');
    expect(levelOf([{ level: 1, label: 'a' }], 1)?.label).toBe('a');
    expect(levelOf([{ level: 1, label: 'a' }], 3)).toBeUndefined();
  });
});
