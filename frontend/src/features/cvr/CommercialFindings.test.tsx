import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CommercialFindings } from './CommercialFindings';
import type { CommercialFinding } from './api';

const finding = (severity: string, message: string, ref = 'p1'): CommercialFinding => ({
  rule_id: 'procurement.line_over_committed',
  severity,
  element_ref: ref,
  message,
  suggestion: 'Check the orders on this line.',
  details: {},
});

describe('CommercialFindings', () => {
  it('renders nothing without findings', () => {
    const { container } = render(<CommercialFindings findings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('lists errors before warnings, with the server message and suggestion', () => {
    render(
      <CommercialFindings
        findings={[
          finding('warning', 'Line 01 commits 110 of 100 budgeted.'),
          finding('error', 'Amounts from 10000 to 20000 reach no approver.', 'step:2'),
        ]}
      />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Amounts from 10000 to 20000 reach no approver.');
    expect(items[1]).toHaveTextContent('Line 01 commits 110 of 100 budgeted.');
    expect(items[1]).toHaveTextContent('Check the orders on this line.');
  });

  it('counts what it does not show', () => {
    const many = Array.from({ length: 5 }, (_, i) => finding('warning', `Finding ${i}`, `p${i}`));
    render(<CommercialFindings findings={many} limit={3} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[3]).not.toHaveTextContent('Finding');
  });
});
