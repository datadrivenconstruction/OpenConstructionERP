// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

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

import { NumbersCheck, readTypedValue, trainerFieldInputId } from './NumbersCheck';
import type { NumbersCheckView } from './types';

afterEach(() => cleanup());

const check: NumbersCheckView = {
  id: 't2-numbers',
  kind: 'numbers',
  prompt: 'Type the overheads amount.',
  fields: [{ key: 'overheads_amount', label: 'Overheads', kind: 'money', currency: 'GBP' }],
};

function renderCheck(props: Partial<Parameters<typeof NumbersCheck>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <NumbersCheck
      check={check}
      courseLocale="en-GB"
      currency="GBP"
      values={{ overheads_amount: '' }}
      verdicts={{}}
      showAllProblems={false}
      onChange={onChange}
      {...props}
    />,
  );
  return { onChange, input: screen.getByLabelText('Overheads') as HTMLInputElement };
}

describe('reading what the learner typed', () => {
  it('reads numbers under the course locale and never guesses', () => {
    expect(readTypedValue('3.581.310,00', 'money', 'de-DE')).toEqual({ status: 'ok', value: '3581310.00' });
    expect(readTypedValue('£3,581,310.00', 'money', 'en-GB')).toEqual({ status: 'ok', value: '3581310.00' });
    expect(readTypedValue('  ', 'money', 'en-GB')).toEqual({ status: 'empty' });
  });

  it('names the decimal mark this course uses when the learner used the other one', () => {
    expect(readTypedValue('2433.12', 'money', 'de-DE')).toEqual({ status: 'error', problem: 'use_comma' });
    expect(readTypedValue('2433,12', 'money', 'en-GB')).toEqual({ status: 'error', problem: 'use_point' });
    expect(readTypedValue('12 apples', 'number', 'en-GB')).toEqual({ status: 'error', problem: 'unreadable' });
  });

  it('accepts only real days for a date and trims text', () => {
    expect(readTypedValue('2026-09-01', 'date', 'en-GB')).toEqual({ status: 'ok', value: '2026-09-01' });
    expect(readTypedValue('2026-02-31', 'date', 'en-GB')).toEqual({ status: 'error', problem: 'unreadable' });
    expect(readTypedValue('  Alderby ', 'text', 'en-GB')).toEqual({ status: 'ok', value: 'Alderby' });
  });
});

describe('NumbersCheck', () => {
  it('labels the field, asks for a decimal keyboard and echoes how a value was read', () => {
    const { input } = renderCheck({ values: { overheads_amount: '2433.12' } });
    expect(input.id).toBe(trainerFieldInputId('t2-numbers', 'overheads_amount'));
    expect(input.getAttribute('inputmode')).toBe('decimal');
    expect(input.getAttribute('lang')).toBe('en-GB');
    expect(screen.getByTestId('trainer-field-echo').textContent).toBe('Read as £2,433.12');
    expect(input.getAttribute('aria-describedby')).toContain(`${input.id}-echo`);
  });

  it('shows a refusal in plain words after the field loses focus, not while typing', () => {
    const { input } = renderCheck({ values: { overheads_amount: '2433,12' } });
    expect(screen.queryByTestId('trainer-field-problem')).toBeNull();
    fireEvent.blur(input);
    expect(screen.getByTestId('trainer-field-problem').textContent).toBe('Use a point for decimals in this course');
    expect(input.getAttribute('aria-invalid')).toBe('true');
  });

  it('shows every refusal at once after a press of Check', () => {
    renderCheck({ values: { overheads_amount: '2433.12' }, courseLocale: 'de-DE', showAllProblems: true });
    expect(screen.getByTestId('trainer-field-problem').textContent).toBe('Use a comma for decimals in this course');
  });

  it('reports each change to the parent', () => {
    const { input, onChange } = renderCheck();
    fireEvent.change(input, { target: { value: '12' } });
    expect(onChange).toHaveBeenCalledWith('overheads_amount', '12');
  });

  it('gives each verdict an icon and words, bound to the input', () => {
    const { input } = renderCheck({ values: { overheads_amount: '2500' }, verdicts: { overheads_amount: 'wrong' } });
    const verdict = screen.getByTestId('trainer-field-verdict');
    expect(verdict.textContent).toBe('Does not match yet');
    expect(verdict.querySelector('svg')).not.toBeNull();
    expect(input.getAttribute('aria-describedby')).toContain(verdict.id);
    cleanup();
    renderCheck({ values: { overheads_amount: '' }, verdicts: { overheads_amount: 'missing' } });
    expect(screen.getByTestId('trainer-field-verdict').textContent).toBe('Missing');
  });
});
