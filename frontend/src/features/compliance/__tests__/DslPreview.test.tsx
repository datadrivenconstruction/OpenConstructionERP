// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DslPreview } from '../DslPreview';

const SAMPLE_YAML = `rule_id: custom.wall.has_fire_rating
name: All wall must have fire rating
severity: warning
scope: wall
expression:
  forEach: wall
  assert:
    "!=": [wall.fire_rating, null]
`;

describe('DslPreview', () => {
  it('renders the empty placeholder when no YAML is supplied', () => {
    render(<DslPreview yaml={null} />);
    expect(screen.getByTestId('dsl-preview-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('dsl-preview-yaml')).not.toBeInTheDocument();
  });

  it('renders YAML content when supplied', () => {
    render(<DslPreview yaml={SAMPLE_YAML} />);
    const block = screen.getByTestId('dsl-preview-yaml');
    expect(block).toBeInTheDocument();
    // Ensure the readable content survives the highlighter.
    expect(block.textContent).toContain('rule_id');
    expect(block.textContent).toContain('custom.wall.has_fire_rating');
    expect(block.textContent).toContain('forEach');
  });

  it('shows a Copy affordance and fires onCopy when clicked', () => {
    const onCopy = vi.fn();
    render(<DslPreview yaml={SAMPLE_YAML} onCopy={onCopy} />);
    const btn = screen.getByTestId('dsl-preview-copy');
    fireEvent.click(btn);
    expect(onCopy).toHaveBeenCalledTimes(1);
  });
});
