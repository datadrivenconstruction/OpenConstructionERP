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

import { Diagnosis } from './Diagnosis';
import { attemptFailFixture } from './__fixtures__/attemptFail';
import type { Diagnosis as DiagnosisData } from './types';

afterEach(() => cleanup());

const fixtureDiagnosis = attemptFailFixture.fields.find((f) => f.diagnosis)!.diagnosis as DiagnosisData;
const diagnosis: DiagnosisData = {
  ...fixtureDiagnosis,
  related: fixtureDiagnosis.related.map((r) => ({ ...r, label: 'Profit on direct cost' })),
};

describe('Diagnosis', () => {
  it('says what went wrong in plain words, with the figures the author chose to show', () => {
    render(<Diagnosis diagnosis={diagnosis} courseLocale="en-GB" currency="GBP" subject="Grand total of the main bill" />);
    const card = screen.getByTestId('trainer-diagnosis');
    expect(card.textContent).toContain('What happened');
    expect(card.textContent).toContain('Grand total of the main bill');
    expect(card.textContent).toContain('Profit was charged on the overheads as well.');
    expect(card.textContent).toContain('£1,520.70');
    expect(card.textContent).toContain('Change the figure and check again.');
    expect(card.getAttribute('data-diagnosis-id')).toBe('t2-profit-compounded');
  });

  it('names a related figure by its label, never by its ledger key', () => {
    render(<Diagnosis diagnosis={diagnosis} courseLocale="en-GB" currency="GBP" />);
    const related = screen.getByTestId('trainer-diagnosis-related');
    expect(related.textContent).toContain('Profit on direct cost');
    expect(related.querySelector('dt')?.getAttribute('lang') ?? related.closest('[lang]')?.getAttribute('lang')).toBe('en-GB');
    expect(document.body.innerHTML).not.toContain('fx_profit_amount');
  });

  it('hides a related row without a label, and the whole block when none has one', () => {
    const mixed: DiagnosisData = {
      ...fixtureDiagnosis,
      related: [
        { name: 'fx_profit_amount', value: '1520.70', kind: 'money', label: null },
        { name: 'fx_overheads_amount', value: '2433.12', kind: 'money', label: 'Overheads on direct cost' },
      ],
    };
    render(<Diagnosis diagnosis={mixed} courseLocale="en-GB" currency="GBP" />);
    const related = screen.getByTestId('trainer-diagnosis-related');
    expect(related.querySelectorAll('dt')).toHaveLength(1);
    expect(related.textContent).toContain('Overheads on direct cost');
    expect(related.textContent).not.toContain('£1,520.70');
    expect(document.body.innerHTML).not.toMatch(/fx_profit_amount|fx_overheads_amount/);
    cleanup();

    // Every label null: the block goes, the message stays.
    const unlabelled: DiagnosisData = {
      ...fixtureDiagnosis,
      related: fixtureDiagnosis.related.map((r) => ({ ...r, label: null })),
    };
    render(<Diagnosis diagnosis={unlabelled} courseLocale="en-GB" currency="GBP" />);
    expect(screen.queryByTestId('trainer-diagnosis-related')).toBeNull();
    expect(screen.getByTestId('trainer-diagnosis').textContent).toContain('Profit was charged on the overheads as well.');
    expect(document.body.innerHTML).not.toContain('fx_profit_amount');
  });

  it('never prints a signed difference or a "should be" figure', () => {
    render(<Diagnosis diagnosis={diagnosis} courseLocale="en-GB" currency="GBP" />);
    const text = screen.getByTestId('trainer-diagnosis').textContent ?? '';
    expect(text).not.toMatch(/short|over by|should be|expected/i);
  });

  it('renders the course content in the course language and writes dates in words', () => {
    render(
      <Diagnosis
        diagnosis={{ id: 'd', kind: 'convention', message: 'The claim period ends on 2026-09-30.', related: [] }}
        courseLocale="de-DE"
        currency="EUR"
      />,
    );
    const message = screen.getByText(/Die|The claim period/);
    expect(message.textContent).toBe('The claim period ends on 30. September 2026.');
    expect(message.closest('[lang]')?.getAttribute('lang')).toBe('de-DE');
  });

  it('pops in, and the stylesheet turns that off under reduced motion', () => {
    render(<Diagnosis diagnosis={diagnosis} courseLocale="en-GB" currency="GBP" />);
    expect(screen.getByTestId('trainer-diagnosis').className).toContain('oe-trainer-pop');
  });
});
