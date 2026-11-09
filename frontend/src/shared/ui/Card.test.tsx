import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Card } from './Card';

describe('Card stacking', () => {
  it('lifts a card that holds focus or an open popup above sibling cards', () => {
    render(<Card data-testid="card">x</Card>);
    const cls = screen.getByTestId('card').className;
    // The card is a stacking context (transform-gpu); without a lift an open
    // dropdown paints under the next card in the page.
    expect(cls).toContain('transform-gpu');
    expect(cls).toContain('relative');
    expect(cls).toContain('focus-within:z-20');
    expect(cls).toContain('has-[[aria-expanded=true]]:z-20');
  });
});
