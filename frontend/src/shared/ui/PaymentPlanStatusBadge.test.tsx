// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The instalment badge prints the server's status in words and colours, and
// never decides the status itself: overdue is what the server says it is.

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PaymentPlanStatusBadge } from './PaymentPlanStatusBadge';

describe('PaymentPlanStatusBadge', () => {
  it.each([
    ['upcoming', 'Upcoming', 'bg-surface-secondary'],
    ['due', 'Due', 'bg-semantic-warning-bg'],
    ['invoiced', 'Invoiced', 'bg-oe-blue-subtle'],
    ['paid', 'Paid', 'bg-semantic-success-bg'],
    ['overdue', 'Overdue', 'bg-semantic-error-bg'],
  ])('shows %s as "%s" in its own colour', (status, label, tone) => {
    render(<PaymentPlanStatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge.closest('span')?.className).toContain(tone);
  });

  it('shows a code it does not know as it came, in the neutral colour', () => {
    render(<PaymentPlanStatusBadge status="disputed" />);
    const badge = screen.getByText('disputed');
    expect(badge.closest('span')?.className).toContain('bg-surface-secondary');
  });
});
