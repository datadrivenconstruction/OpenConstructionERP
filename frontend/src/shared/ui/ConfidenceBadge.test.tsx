import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConfidenceBadge, bandForScore } from './ConfidenceBadge';

describe('bandForScore', () => {
  it('thresholds with the provisional cutoffs', () => {
    expect(bandForScore(0.95)).toBe('high');
    expect(bandForScore(0.8)).toBe('high');
    expect(bandForScore(0.79)).toBe('medium');
    expect(bandForScore(0.5)).toBe('medium');
    expect(bandForScore(0.49)).toBe('low');
    expect(bandForScore(0)).toBe('low');
  });
});

describe('ConfidenceBadge', () => {
  it('renders a translated label for a backend-owned level', () => {
    render(<ConfidenceBadge level="high" />);
    expect(screen.getByText('High confidence')).toBeInTheDocument();
  });

  it('never re-thresholds a given level (level wins over score)', () => {
    // level says high even though the score would band as low
    render(<ConfidenceBadge level="high" score={0.1} />);
    expect(screen.getByText('High confidence')).toBeInTheDocument();
  });

  it('bands a raw score when no level is given', () => {
    render(<ConfidenceBadge score={0.4} />);
    expect(screen.getByText('Low confidence')).toBeInTheDocument();
  });

  it('accepts the cost-certainty colour bands', () => {
    render(<ConfidenceBadge level="yellow" />);
    expect(screen.getByText('Medium confidence')).toBeInTheDocument();
  });

  it('renders nothing when neither level nor score is provided', () => {
    const { container } = render(<ConfidenceBadge />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing for an unrecognised level', () => {
    const { container } = render(<ConfidenceBadge level="banana" />);
    expect(container.firstChild).toBeNull();
  });
});
