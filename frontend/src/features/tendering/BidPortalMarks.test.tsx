// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A bid that came in through a bidder link tells the buyer two things the
// price alone does not: that it arrived after the deadline, and what the firm
// wrote alongside its prices.

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { BidPortalMarks, bidPortalMarks } from './BidPortalMarks';

describe('marks on a bid from a bidder link', () => {
  it('shows the late mark and the bidder note', () => {
    render(
      <BidPortalMarks metadata={{ source: 'bid_portal', late: true, bidder_note: 'Prices valid for 60 days' }} />,
    );
    expect(screen.getByText('Late')).toBeTruthy();
    expect(screen.getByTestId('bid-portal-note').textContent).toContain('Prices valid for 60 days');
  });

  it('shows nothing for an on-time bid without a note', () => {
    const { container } = render(<BidPortalMarks metadata={{ source: 'bid_portal', late: false, bidder_note: '  ' }} />);
    expect(container.textContent).toBe('');
  });

  it('ignores the same keys on a bid staff typed in', () => {
    expect(bidPortalMarks({ late: true, bidder_note: 'typed by staff' })).toEqual({ late: false, note: '' });
    expect(bidPortalMarks(undefined)).toEqual({ late: false, note: '' });
  });
});
