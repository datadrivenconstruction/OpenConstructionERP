// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      const o = (typeof opts === 'string' ? { defaultValue: opts } : (opts ?? {})) as Record<string, unknown>;
      const template = typeof o.defaultValue === 'string' ? o.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, n: string) => String(o[n] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { ReadbackList } from './ReadbackList';
import { readbackFixture } from './__fixtures__/readback';
import { taskFixture } from './__fixtures__/task';
import type { ReadbackItemView, ReadbackValue } from './types';

afterEach(() => cleanup());

describe('ReadbackList', () => {
  it('shows a match, and a mismatch with the value the project holds', () => {
    render(
      <ReadbackList items={taskFixture.readback} values={readbackFixture.items} courseLocale="en-GB" currency="GBP" />,
    );
    const rb0 = screen.getByTestId('trainer-readback-rb0');
    expect(rb0.getAttribute('data-state')).toBe('mismatch');
    expect(rb0.textContent).toContain('Grand total of the main bill');
    expect(rb0.textContent).toContain('Your project shows £34,489.48');
    const rb1 = screen.getByTestId('trainer-readback-rb1');
    expect(rb1.getAttribute('data-state')).toBe('match');
    expect(rb1.textContent).toContain('Matches your answer');
    expect(screen.getByTestId('trainer-readback-summary').textContent).toBe('1 of 2 match');
  });

  it('tells the learner what to do when a line is unknown for a reason it knows', () => {
    const items: ReadbackItemView[] = [
      { id: 'lev', what: 'Lowest normalised bid', kind: 'money' },
      { id: 'other', what: 'Awarded bidder', kind: 'text' },
    ];
    const values: ReadbackValue[] = [
      { id: 'lev', state: 'unknown', app_value: null, kind: 'money', reason_key: 'trainer.readback.open_leveling' },
      { id: 'other', state: 'unknown', app_value: null, kind: 'text', reason_key: 'trainer.readback.something_new' },
    ];
    render(<ReadbackList items={items} values={values} courseLocale="en-GB" currency="GBP" />);
    expect(screen.getByTestId('trainer-readback-lev').textContent).toContain(
      'Open the levelling view and press Compute Leveling',
    );
    expect(screen.getByTestId('trainer-readback-other').textContent).toContain('Not readable yet');
    expect(screen.getByTestId('trainer-readback-other').textContent).not.toContain('trainer.readback');
  });

  it('reads a line the API has not answered yet as unknown', () => {
    render(<ReadbackList items={taskFixture.readback} values={undefined} courseLocale="en-GB" currency="GBP" loading />);
    expect(screen.getByTestId('trainer-readback-rb0').getAttribute('data-state')).toBe('unknown');
  });

  it('renders nothing for a task without readback lines', () => {
    const { container } = render(<ReadbackList items={[]} values={[]} courseLocale="en-GB" currency="GBP" />);
    expect(container.innerHTML).toBe('');
  });
});
