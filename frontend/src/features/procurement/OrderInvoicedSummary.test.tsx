// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { OrderInvoicedSummary } from './OrderInvoicedSummary';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
    i18n: { language: 'en' },
  }),
}));

describe('OrderInvoicedSummary', () => {
  it('shows invoiced to date against the order value, both net', () => {
    render(<OrderInvoicedSummary invoiced="45000.00" ordered="50000.00" currency="EUR" />);
    const box = screen.getByTestId('po-invoiced-summary');
    expect(box.textContent).toContain('Invoiced (net)');
    expect(box.textContent).toMatch(/45[,.\s\u00a0\u202f]?000/);
    expect(box.textContent).toMatch(/50[,.\s\u00a0\u202f]?000/);
    expect(box.textContent).not.toContain('Invoiced above the order value');
  });

  it('flags an order invoiced above its value', () => {
    render(<OrderInvoicedSummary invoiced="55000" ordered="50000" currency="EUR" />);
    expect(screen.getByText('Invoiced above the order value')).toBeInTheDocument();
  });
});
