// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// UsageBadge is the single indicator next to a cost item's price. These
// tests pin the founder bug fix (2026-06-06): one control, never two
// contradictory circles, and a used pill is never red - a first use shows
// the reassuring amber "in use" tone, not an alarm.

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { UsageBadge } from './UsageBadge';

function band(over = {}) {
  return {
    cost_item_id: 'item-1',
    frequency: 1,
    age_days: 0,
    source: 'manual',
    confidence_badge: 'yellow',
    last_used_at: '2026-06-06T00:00:00Z',
    ...over,
  };
}

describe('UsageBadge', () => {
  it('renders the quiet outlined dot when unused (never an alarm colour)', () => {
    const { container } = render(<UsageBadge count={0} />);
    const el = container.querySelector('[data-usage]');
    expect(el).toBeTruthy();
    expect(el?.getAttribute('data-usage')).toBe('0');
    // Unused must not carry any error/red styling.
    expect(el?.className).not.toMatch(/error|red/);
  });

  it('renders exactly one indicator with the count when used', () => {
    const { container } = render(<UsageBadge count={1} band={band()} />);
    const indicators = container.querySelectorAll('[data-usage]');
    expect(indicators.length).toBe(1);
    const el = indicators[0];
    expect(el.getAttribute('data-usage')).toBe('1');
    expect(el.textContent).toContain('1');
  });

  it('exposes the certainty band via data-band for tests', () => {
    const { container } = render(<UsageBadge count={3} band={band({ frequency: 3 })} />);
    expect(container.querySelector('[data-band="yellow"]')).toBeTruthy();
  });

  it('uses success (green) tinting only when the band is green', () => {
    const { container } = render(
      <UsageBadge count={12} band={band({ frequency: 12, confidence_badge: 'green' })} />,
    );
    const el = container.querySelector('[data-usage]');
    expect(el?.className).toMatch(/semantic-success/);
    expect(el?.className).not.toMatch(/amber/);
  });

  it('uses amber tinting for a yellow band - a used pill is never red', () => {
    const { container } = render(<UsageBadge count={2} band={band({ frequency: 2 })} />);
    const el = container.querySelector('[data-usage]');
    expect(el?.className).toMatch(/amber/);
    expect(el?.className).not.toMatch(/semantic-error|\bred\b/);
  });

  it('tints a stale (red-band) used item amber, never red', () => {
    const { container } = render(
      <UsageBadge count={1} band={band({ confidence_badge: 'red', age_days: 1500 })} />,
    );
    const el = container.querySelector('[data-usage]');
    // The certainty band is exposed faithfully...
    expect(el?.getAttribute('data-band')).toBe('red');
    // ...but the visual tone is amber, not an error red.
    expect(el?.className).toMatch(/amber/);
    expect(el?.className).not.toMatch(/semantic-error/);
  });

  it('folds freshness into the tooltip when band data is present', () => {
    const { container } = render(<UsageBadge count={2} band={band({ frequency: 2 })} />);
    const el = container.querySelector('[data-usage]');
    // The combined tooltip folds in both the count and the freshness phrase.
    // (The test i18n mock returns the raw defaultValue template without
    // interpolating, so we assert on the template placeholders/words.)
    expect(el?.getAttribute('title')).toMatch(/count/);
    expect(el?.getAttribute('title')).toMatch(/last/);
  });
});
