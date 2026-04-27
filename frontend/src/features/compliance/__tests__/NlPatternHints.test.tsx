// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NlPatternHints } from '../NlPatternHints';

const PATTERNS = [
  { pattern_id: 'must_have', name_key: 'compliance.nl.pattern.must_have', confidence: 0.9 },
  { pattern_id: 'value_at_least', name_key: 'compliance.nl.pattern.value_at_least', confidence: 0.92 },
  { pattern_id: 'count_at_least', name_key: 'compliance.nl.pattern.count_at_least', confidence: 0.86 },
];

describe('NlPatternHints', () => {
  it('renders all supplied patterns with examples', () => {
    render(<NlPatternHints patterns={PATTERNS} />);
    expect(screen.getByTestId('nl-pattern-must_have')).toBeInTheDocument();
    expect(screen.getByTestId('nl-pattern-value_at_least')).toBeInTheDocument();
    expect(screen.getByTestId('nl-pattern-count_at_least')).toBeInTheDocument();
    // Example string is rendered for each known pattern.
    expect(
      screen.getByText('all walls must have fire_rating'),
    ).toBeInTheDocument();
  });

  it('invokes onPick with the example when clicked', () => {
    const onPick = vi.fn();
    render(<NlPatternHints patterns={PATTERNS} onPick={onPick} />);
    const example = screen.getByText('there must be at least 3 walls');
    fireEvent.click(example);
    expect(onPick).toHaveBeenCalledWith('there must be at least 3 walls');
  });
});
