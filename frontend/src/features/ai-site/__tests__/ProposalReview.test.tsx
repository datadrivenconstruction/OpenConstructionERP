// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProposalReview } from '../ProposalReview';


type Item = { id: string; confidence: number; text: string };
const items: Item[] = [
  { id: 'a0', confidence: 0.9, text: 'First' },
  { id: 'a1', confidence: 0.4, text: 'Second' },
  { id: 'a2', confidence: 0.6, text: 'Third' },
];

function setup(degraded = false) {
  const onConfirm = vi.fn();
  render(
    <MemoryRouter>
      <ProposalReview<Item>
        items={items}
        degraded={degraded}
        onConfirm={onConfirm}
        onRejectAll={vi.fn()}
        renderItem={(i) => <span>{i.text}</span>}
        renderEdit={(i, _d, set) => (
          <input aria-label="text" defaultValue={i.text} onChange={(e) => set({ text: e.target.value })} />
        )}
      />
    </MemoryRouter>,
  );
  return onConfirm;
}

describe('ProposalReview', () => {
  it('confirm is disabled until something is accepted and sends only accepted items', () => {
    const onConfirm = setup();
    const confirm = screen.getByTestId('proposal-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByTestId('proposal-accept-a0'));
    fireEvent.click(screen.getByTestId('proposal-reject-a1'));
    fireEvent.click(screen.getByTestId('proposal-accept-a2'));
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith([{ id: 'a0' }, { id: 'a2' }]);
  });

  it('sends edits with an edited item', () => {
    const onConfirm = setup();
    fireEvent.click(screen.getByTestId('proposal-edit-a1'));
    fireEvent.change(screen.getByLabelText('text'), { target: { value: 'Changed' } });
    fireEvent.click(screen.getByTestId('proposal-confirm'));
    expect(onConfirm).toHaveBeenCalledWith([{ id: 'a1', edits: { text: 'Changed' } }]);
  });

  it('shows the degraded banner only without a provider', () => {
    setup(true);
    expect(screen.getByTestId('site-ai-degraded-banner').textContent).toContain(
      'No AI provider configured: showing rule-based result',
    );
  });

  it('shows no banner when a provider answered', () => {
    setup(false);
    expect(screen.queryByTestId('site-ai-degraded-banner')).toBeNull();
  });
});
