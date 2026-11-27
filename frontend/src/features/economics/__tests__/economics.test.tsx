// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The economics screens: the figures arrive as decimal strings and are shown as
// the server sent them, an unknown figure is a dash and never zero, and every
// message key the feature uses resolves in English and German with the same
// placeholders.

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('react-i18next', async () => {
  const table = (await import('@/app/locales/en')).default.translation as Record<string, string>;
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        let text = table[key] ?? (opts?.defaultValue as string | undefined) ?? key;
        for (const [k, v] of Object.entries(opts ?? {})) {
          if (k !== 'defaultValue') text = text.split(`{{${k}}}`).join(String(v));
        }
        return text;
      },
      i18n: { language: 'en', exists: () => true },
    }),
    initReactI18next: { type: '3rdParty', init: () => undefined },
  };
});

import en from '@/app/locales/en';
import de from '@/app/locales/de';

import type { BusinessCase, CostFrame, Financing, Registers } from '../api';
import { BusinessCasePanel } from '../BusinessCasePanel';
import { CostFramePanel } from '../CostFramePanel';
import { ConfirmDelete, FindingList, isDecimal, cleanDecimal } from '../EconomicsBits';
import { FinancingPanel } from '../FinancingPanel';
import {
  BLOCK,
  FINDING,
  FLOW_KIND,
  INSURANCE_KIND,
  INSURANCE_STATUS,
  PLAN_STATUS,
  PROCESS_AREA,
  SECURITY_KIND,
  SECURITY_STATUS,
  SOURCE_KIND,
  VAT_TREATMENT,
} from '../labels';
import { RegistersPanel } from '../RegistersPanel';

vi.mock('../hooks', () => ({
  useEconomicsAction: () => async () => undefined,
}));

afterEach(cleanup);

const CASE: BusinessCase = {
  currency: 'EUR',
  discount_rate_pct: '3.0000',
  horizon_years: 40,
  frame_total: '59200000.0000',
  lines: [
    {
      id: 'a',
      kind: 'investment',
      label: 'Construction',
      mode: 'total',
      source: 'cost_frame',
      amount: '59200000.0000',
      year_from: 0,
      year_to: 2,
      escalation_pct: '0.0000',
      notes: '',
    },
  ],
  cash_flow: [],
  key_figures: {
    total_investment: '59200000.0000',
    total_revenue: '1000.5000',
    total_operating_cost: '0',
    residual_value: '0',
    net_cash_flow: '0',
    npv: '-1234567.8900',
    irr_pct: null,
    payback_year: null,
    benefit_cost_ratio: null,
    yield_on_cost_pct: null,
  },
};

const FINANCING: Financing = {
  currency: 'EUR',
  requirement: '100.00',
  coverage: { sources_total: '90.00', shortfall: '10.00', surplus: '0.00', covered: false, coverage_pct: '90.00' },
  sources: [
    {
      id: 's1',
      kind: 'equity',
      name: 'Own funds',
      amount: '90.00',
      share_pct: '100.00',
      interest_rate_pct: null,
      funding_application_id: null,
      award: null,
      notes: '',
      tranche_total: '90.00',
      tranches: [{ id: 't1', due_on: '2027-01-15', amount: '90.00', status: 'planned', condition: '', drawn_on: null }],
    },
  ],
};

describe('business case panel', () => {
  it('shows an unknown figure as a dash and keeps the sign of a negative value', () => {
    render(<BusinessCasePanel projectId="p" data={CASE} editable={false} />);
    expect(screen.getByTestId('economics-figure-irr').textContent).toContain('-');
    expect(screen.getByTestId('economics-figure-payback').textContent).not.toContain('0');
    const npv = screen.getByTestId('economics-figure-npv').textContent ?? '';
    expect(npv).toContain('1,234,567.89');
    expect(npv).toContain('-');
  });

  it('offers no editing to a reader', () => {
    render(<BusinessCasePanel projectId="p" data={CASE} editable={false} />);
    expect(screen.queryByText('Add a line')).toBeNull();
  });
});

describe('financing panel', () => {
  it('states the shortfall apart from the surplus', () => {
    render(<FinancingPanel projectId="p" data={FINANCING} editable />);
    expect(screen.getByTestId('economics-shortfall').textContent).toContain('10.00');
    expect(screen.getAllByTestId('economics-source')).toHaveLength(1);
    expect(screen.getByText('Add a source')).toBeTruthy();
  });
});

const FRAME: CostFrame = {
  classification_standard: 'din276',
  currency: 'EUR',
  bill: { id: 'b', name: 'Bill', currency: 'EUR', bill_count: 1 },
  lines: [
    {
      id: 'f1',
      code: '300',
      title: 'Bauwerk',
      basis: '',
      amount: '1000000.0000',
      estimate: '900000.0000',
      committed: null,
      variance: '-100000.0000',
      variance_pct: '-10.00',
      headroom: '100000.0000',
    },
  ],
  markups: [],
  totals: {
    lines: '1000000.0000',
    markup_allowance: '0.0000',
    frame: '1000000.0000',
    estimate_direct: '900000.0000',
    estimate_assigned: '900000.0000',
    estimate_unassigned: '0.0000',
    unassigned_count: 0,
    markups: '0.0000',
    estimate: '900000.0000',
    reserve: '100000.0000',
    variance: '-100000.0000',
    variance_pct: '-10.00',
    committed: null,
    committed_unassigned: null,
    committed_available: false,
    committed_reason: '',
  },
};

const REGISTERS: Registers = {
  securities: [
    {
      id: 's1',
      kind: 'performance',
      description: 'Vertragserfuellungsbuergschaft',
      amount: '2400000.0000',
      issuer: 'Bank',
      beneficiary: '',
      reference: 'VE-1',
      valid_from: '2026-01-01',
      valid_until: '2026-02-01',
      status: 'in_place',
      lapsed: true,
      notes: '',
    },
  ],
  insurances: [],
  tax: {
    vat_treatment: 'exempt',
    input_tax_deduction: false,
    notes: '',
    confirmed: true,
    confirmed_by: 'u1',
    confirmed_by_name: 'Maria Lindner',
    confirmed_at: '2026-08-01T10:00:00Z',
  },
  process: [{ area: 'receivables', description: 'Rent invoicing', owner: 'Accounting', status: 'set_up', set_up_on: '2026-08-01', notes: '' }],
  state: { securities: false, insurance: false, tax: true, receivables_payables: false, administration: false },
  findings: [],
};

describe('cost frame reconciliation', () => {
  it('shows the estimate, the reserve and the frame so the numbers add up on screen', () => {
    render(<CostFramePanel projectId="p" frame={FRAME} markupAllowance="0" editable={false} />);
    const box = screen.getByTestId('economics-reconciliation').textContent ?? '';
    expect(box).toContain('900,000');
    expect(box).toContain('1,000,000');
    expect(screen.getByTestId('economics-reserve').textContent).toContain('100,000');
  });
});

describe('delete asks first', () => {
  it('removes the row only after the dialog is confirmed', () => {
    const onConfirm = vi.fn();
    render(<ConfirmDelete label="Delete the line" title="Delete this entry?" message="Sure?" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByLabelText('Delete the line'));
    expect(screen.getByText('Delete this entry?')).toBeTruthy();
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('does nothing when the dialog is cancelled', () => {
    const onConfirm = vi.fn();
    render(<ConfirmDelete label="Delete the line" title="Delete this entry?" message="Sure?" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByLabelText('Delete the line'));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe('registers panel', () => {
  it('shows a reader the registers with editing disabled, with the confirmer of the tax treatment by name', () => {
    render(<RegistersPanel projectId="p" data={REGISTERS} canEdit={false} currency="EUR" />);
    expect(screen.getAllByTestId('economics-security')).toHaveLength(1);
    expect(screen.getByTestId('economics-tax').textContent).toContain('Maria Lindner');
    expect(screen.getByText('Add a security').closest('button')).toBeDisabled();
    expect(screen.getByLabelText('Delete the security')).toBeDisabled();
    expect(screen.getByText('Save the tax treatment').closest('button')).toBeDisabled();
  });

  it('offers editing to an editor even though the plan itself is not editable', () => {
    render(<RegistersPanel projectId="p" data={REGISTERS} canEdit currency="EUR" />);
    expect(screen.getByText('Add a security')).toBeTruthy();
    expect(screen.getByLabelText('Delete the security')).toBeTruthy();
    expect(screen.getByText('Save the tax treatment')).toBeTruthy();
  });

  it('marks the check list from the server state', () => {
    render(<RegistersPanel projectId="p" data={REGISTERS} canEdit={false} currency="EUR" />);
    expect(screen.getByTestId('economics-checklist').querySelectorAll('li')).toHaveLength(5);
  });
});

describe('findings and inputs', () => {
  it('words a finding and falls back to its code for an unknown one', () => {
    render(
      <FindingList
        findings={[
          { code: 'financing_shortfall', ref: 'project', severity: 'error' },
          { code: 'some_new_code', ref: 'x', severity: 'warning' },
        ]}
      />,
    );
    expect(screen.getByText('The sources of finance do not cover the investment.')).toBeTruthy();
    expect(screen.getByText('some new code')).toBeTruthy();
  });

  it('reads a decimal with a comma and refuses anything else', () => {
    expect(isDecimal('12,50')).toBe(true);
    expect(cleanDecimal(' 12,50 ')).toBe('12.50');
    expect(isDecimal('1e5')).toBe(false);
    expect(isDecimal('')).toBe(false);
  });
});

describe('economics i18n keys', () => {
  const featureDir = join(__dirname, '..');
  const sources = readdirSync(featureDir)
    .filter((f) => /\.(ts|tsx)$/.test(f))
    .map((f) => readFileSync(join(featureDir, f), 'utf-8'))
    .join('\n');
  const used = new Set<string>();
  for (const m of sources.matchAll(/\bt\(\s*'(economics\.[A-Za-z0-9_.]+)'/g)) used.add(m[1]!);
  for (const map of [
    PLAN_STATUS,
    FLOW_KIND,
    SOURCE_KIND,
    FINDING,
    BLOCK,
    SECURITY_KIND,
    SECURITY_STATUS,
    INSURANCE_KIND,
    INSURANCE_STATUS,
    VAT_TREATMENT,
    PROCESS_AREA,
  ]) {
    for (const [key] of Object.values(map)) used.add(key);
  }
  const placeholders = (text: string) => [...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort();

  it('finds the keys it is meant to check', () => {
    expect(used.size).toBeGreaterThan(100);
    expect(used.has('economics.ui.title')).toBe(true);
  });

  it('has every key in English and German with the same placeholders', () => {
    for (const key of used) {
      const english = en.translation[key];
      const german = de.translation[key];
      expect(english, `en ${key}`).toBeTruthy();
      expect(german, `de ${key}`).toBeTruthy();
      expect(placeholders(german!), key).toEqual(placeholders(english!));
    }
  });

  it('names every finding code the server can raise', () => {
    const rules = readFileSync(join(__dirname, '../../../../../backend/app/modules/economics/rules.py'), 'utf-8');
    const block = rules.slice(rules.indexOf('CODES: dict'), rules.indexOf('@dataclass'));
    const codes = [...block.matchAll(/^\s+"(\w+)": (?:ERROR|WARNING),/gm)].map((m) => m[1]!);
    expect(codes.length).toBeGreaterThan(20);
    for (const code of codes) expect(FINDING[code], code).toBeTruthy();
  });
});
