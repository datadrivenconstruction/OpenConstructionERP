// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

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

import { ChoiceCheck } from './ChoiceCheck';
import { taskFixture } from './__fixtures__/task';
import type { ChoiceCheckView, FieldResult } from './types';

afterEach(() => cleanup());

const trace = taskFixture.checks.find((c) => c.kind === 'trace') as ChoiceCheckView;

function result(verdict: FieldResult['verdict'], observed: string, feedback: string | null): FieldResult {
  return { key: trace.id, source: 'panel', verdict, observed, diagnosis: null, feedback };
}

describe('ChoiceCheck', () => {
  it('offers every option as a pressable button, in the course language', () => {
    const onPick = vi.fn();
    render(<ChoiceCheck check={trace} courseLocale="en-GB" chosen={null} pendingIndex={null} result={null} onPick={onPick} />);
    const section = screen.getByTestId(`trainer-choice-${trace.id}`);
    expect(within(section).getByText('Trace')).toBeTruthy();
    const options = screen.getAllByTestId('trainer-choice-option');
    expect(options).toHaveLength(3);
    expect(options.every((o) => o.getAttribute('aria-pressed') === 'false')).toBe(true);
    fireEvent.click(options[1]!);
    expect(onPick).toHaveBeenCalledWith(1);
  });

  it('never sends or shows which option is correct before a check', () => {
    render(<ChoiceCheck check={trace} courseLocale="en-GB" chosen={null} pendingIndex={null} result={null} onPick={vi.fn()} />);
    expect(screen.queryByTestId('trainer-choice-verdict')).toBeNull();
    expect(JSON.stringify(trace)).not.toContain('correct');
  });

  it('shows the feedback of a wrong pick and lets the learner pick again', () => {
    const onPick = vi.fn();
    render(
      <ChoiceCheck
        check={trace}
        courseLocale="en-GB"
        chosen={1}
        pendingIndex={null}
        result={result('wrong', '1', 'Overheads are not part of the profit base here.')}
        onPick={onPick}
      />,
    );
    const verdict = screen.getByTestId('trainer-choice-verdict');
    expect(verdict.textContent).toContain('Not this one');
    expect(verdict.textContent).toContain('Overheads are not part of the profit base here.');
    const options = screen.getAllByTestId('trainer-choice-option');
    expect(options[1]!.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(options[0]!);
    expect(onPick).toHaveBeenCalledWith(0);
  });

  it('closes the question on a right pick: no buttons are left that do nothing', () => {
    render(
      <ChoiceCheck
        check={trace}
        courseLocale="en-GB"
        chosen={0}
        pendingIndex={null}
        result={result('ok', '0', 'Yes: 30414.00 x 5% = 1520.70.')}
        onPick={vi.fn()}
      />,
    );
    expect(screen.queryAllByTestId('trainer-choice-option')).toHaveLength(0);
    expect(screen.getByTestId('trainer-choice-verdict').textContent).toContain('Right');
    expect(screen.getByText('Direct cost only.').closest('li')?.getAttribute('data-picked')).toBe('true');
  });

  it('ignores a second pick while one is being checked', () => {
    const onPick = vi.fn();
    render(<ChoiceCheck check={trace} courseLocale="en-GB" chosen={2} pendingIndex={2} result={null} onPick={onPick} />);
    const options = screen.getAllByTestId('trainer-choice-option');
    expect(options[2]!.getAttribute('aria-busy')).toBe('true');
    fireEvent.click(options[0]!);
    expect(onPick).not.toHaveBeenCalled();
  });
});
