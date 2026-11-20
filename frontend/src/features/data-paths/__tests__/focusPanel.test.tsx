import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  useModuleChanges: () => ({
    isLoading: false,
    data: {
      module: 'oe_boq',
      days: 30,
      changes: [{ module: 'oe_tendering', entity: 'tender_package', entity_id: '1', action: 'update', at: new Date().toISOString(), user: 'A. Estimator' }],
    },
  }),
}));

import type { EdgeOut, MapModule, ModuleFocus } from '../api';
import { FocusPanel, type TraceState } from '../FocusPanel';
import { abbreviate } from '../RoleHex';

const mod = (name: string): MapModule => ({
  name,
  display_name: name,
  category: '',
  declared: true,
  installed: true,
  why: '',
  roles: [],
  count: null,
  counts: {},
});
const edge = (source: string, target: string): EdgeOut => ({
  source,
  target,
  kind: 'declared',
  details: [],
  importance: 'high',
  label: '',
  count: null,
  active: true,
  state: 'ok',
});

const MODULES = ['oe_takeoff', 'oe_boq', 'oe_tendering', 'oe_contracts', 'oe_finance'].map(mod);
const EDGES = [edge('oe_takeoff', 'oe_boq'), edge('oe_boq', 'oe_tendering'), edge('oe_tendering', 'oe_contracts')];
const INFO: ModuleFocus = {
  module: 'oe_boq',
  declared: true,
  why: 'Priced scope',
  roles: ['estimator'],
  duties: [{ role: 'estimator', label: 'Prices the positions' }],
  external: [],
  rules: [{ rule_id: 'boq.quantity_positive', name: 'Quantities are positive', severity: 'error' }],
  traces: [
    {
      id: 'takeoff_to_contract',
      label: 'From takeoff to contract',
      summary: '',
      steps: [
        { module: 'oe_takeoff', label: 'Takeoff', via: '' },
        { module: 'oe_boq', label: 'Position', via: '' },
        { module: 'oe_tendering', label: 'Package', via: '' },
        { module: 'oe_contracts', label: 'Contract', via: '' },
      ],
      at: [1],
    },
  ],
};

function mount(trace: TraceState | null, onTrace = vi.fn()) {
  render(
    <MemoryRouter>
      <FocusPanel
        focus="oe_boq"
        info={INFO}
        modules={MODULES}
        edges={EDGES}
        technical={false}
        projectId="p1"
        downstream={['oe_tendering']}
        trace={trace}
        onTrace={onTrace}
        onOpen={vi.fn()}
        onRefocus={vi.fn()}
      />
    </MemoryRouter>,
  );
  return onTrace;
}

afterEach(cleanup);

describe('FocusPanel', () => {
  it('shows impact: 2 of 4 other modules downstream is 50%, medium', () => {
    mount(null);
    const impact = screen.getByTestId('dp-impact');
    expect(impact.textContent).toContain('50%');
    expect(impact.textContent).toContain('Medium impact');
    expect(impact.textContent).toContain('Modules downstream: 2');
  });

  it('lists the inputs and the validation rules that guard them', () => {
    mount(null);
    expect(screen.getByTestId('dp-inputs').textContent).toContain('Takeoff');
    expect(screen.getByTestId('dp-checked').textContent).toContain('Quantities are positive');
  });

  it('starts a trace at the focused step and plays from the start', () => {
    const onTrace = mount(null);
    expect(screen.getByTestId('dp-trace').textContent).toContain('Step 2 of 4');
    fireEvent.click(screen.getByTestId('dp-trace-play'));
    expect(onTrace).toHaveBeenCalledWith({ id: 'takeoff_to_contract', step: 0, playing: true });
  });

  it('shows the recent change downstream with who made it', () => {
    mount(null);
    expect(screen.getByTestId('dp-changes').textContent).toContain('A. Estimator');
  });
});

describe('abbreviate', () => {
  it('takes initials of two words and two letters of one', () => {
    expect(abbreviate('Site manager')).toBe('SM');
    expect(abbreviate('Estimator')).toBe('ES');
    expect(abbreviate('Инженер')).toBe('ИН');
  });
});
