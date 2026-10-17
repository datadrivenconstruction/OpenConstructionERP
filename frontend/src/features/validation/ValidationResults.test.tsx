// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useState } from 'react';
import { ValidationResults } from './ValidationResults';
import type { FindingFilter, FindingLike } from './validationFindings';

const HASH = 'b51f645f-1111-2222-3333-444455556666';

function finding(over: Partial<FindingLike>): FindingLike {
  return {
    rule_id: 'boq_quality.unit_rate_in_range',
    rule_name: 'Unit Rate Anomaly Detection',
    severity: 'warning',
    passed: false,
    message: 'Unit rate 950.00 is more than 5x the median',
    element_ref: HASH,
    suggestion: 'Check the unit rate',
    ...over,
  };
}

function Harness({ findings }: { findings: FindingLike[] }) {
  const [filter, setFilter] = useState<FindingFilter>('problems');
  return (
    <MemoryRouter>
      <ValidationResults
        findings={findings}
        totalChecks={findings.length}
        filter={filter}
        onFilterChange={setFilter}
        positions={new Map([[HASH, { ordinal: '01.02.0030', description: 'Reinforced concrete wall C30/37' }]])}
        boqs={new Map([['boq-1', 'Main bill']])}
        boqId="boq-1"
        ruleHint={() => null}
      />
    </MemoryRouter>
  );
}

describe('ValidationResults', () => {
  it('opens on the problems, grouped by rule, with the position and message inline', () => {
    const passes = Array.from({ length: 30 }, (_, i) =>
      finding({ passed: true, message: 'OK', element_ref: `pass-${i}`, suggestion: null }),
    );
    render(<Harness findings={[...passes, finding({})]} />);

    expect(screen.getByRole('button', { name: /^Problems\s*1$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('Unusually high unit rate')).toHaveLength(1);
    expect(screen.getByText('01.02.0030')).toBeInTheDocument();
    expect(screen.getByText('Reinforced concrete wall C30/37')).toBeInTheDocument();
    expect(screen.getByText('Unit rate 950.00 is more than 5x the median')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open in BOQ/ })).toHaveAttribute(
      'href',
      `/boq/boq-1?highlight=${HASH}`,
    );
    expect(screen.queryByText(/b51f645f/)).toBeNull();
    expect(screen.queryByText('OK')).toBeNull();
  });

  it('shows a success state when nothing failed, with the passes one click away', () => {
    render(<Harness findings={[finding({ passed: true, message: 'OK', suggestion: null })]} />);
    expect(screen.getByText('No problems found')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Show passed checks/ }));
    expect(screen.getByRole('button', { name: /^(Passed|validation\.filter_passed)\s*1$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('OK')).toBeInTheDocument();
  });

  it('offers search past twenty findings and filters by position text', () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      finding({ element_ref: null, message: `Finding number ${i}` }),
    );
    render(<Harness findings={[...many, finding({})]} />);
    const box = screen.getByRole('searchbox');
    fireEvent.change(box, { target: { value: 'concrete wall' } });
    expect(screen.getByText('01.02.0030')).toBeInTheDocument();
    expect(screen.queryByText('Finding number 3')).toBeNull();
  });
});
