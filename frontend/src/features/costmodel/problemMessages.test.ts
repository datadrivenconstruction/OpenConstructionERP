import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { problemMessage } from './problemMessages';

// Echo the key, so the test sees which sentence a problem maps to.
const t = ((key: string) => key) as unknown as TFunction;

describe('problemMessage', () => {
  it('names a heading or closed account target instead of the generic failure', () => {
    expect(problemMessage(t, 'account_not_postable')).toBe('costmodel.problem.account_not_postable');
  });

  it('falls back to the generic sentence for a problem it does not know', () => {
    expect(problemMessage(t, 'something_new')).toBe('costmodel.problem.unknown');
  });
});
