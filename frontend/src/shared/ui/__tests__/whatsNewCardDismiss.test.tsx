// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dashboard's What's new card closes for its release. It used to leave a
// "What's new" pill on the dashboard on every visit after the close, so the
// card could never really be put away. Now the pill belongs to the visit in
// which the card was closed (to undo a close by mistake), and later visits
// show nothing until a newer feature release.
//
// Run:  npx vitest run src/shared/ui/__tests__/whatsNewCardDismiss.test.tsx
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { WhatsNewCard } from '../WhatsNewCard';

const LAST_SEEN_KEY = 'oe.last_seen_version';

function renderCard(version: string) {
  return render(
    <MemoryRouter>
      <WhatsNewCard versionOverride={version} />
    </MemoryRouter>,
  );
}

function cardRegion(): HTMLElement | null {
  return screen.queryByRole('region');
}

function reopenPill(): HTMLElement | null {
  return screen.queryByRole('button', { name: "What's new" });
}

beforeEach(() => {
  localStorage.clear();
});

describe("the What's new card", () => {
  it('shows on the first visit of a release', () => {
    renderCard('18.0.0');
    expect(cardRegion()).not.toBeNull();
  });

  it('closes to a reopen pill for the rest of that visit', async () => {
    renderCard('18.0.0');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    expect(cardRegion()).toBeNull();
    expect(reopenPill()).not.toBeNull();
    expect(localStorage.getItem(LAST_SEEN_KEY)).toBe('18.0.0');
  });

  it('shows nothing at all on the next visit after a close', () => {
    localStorage.setItem(LAST_SEEN_KEY, '18.0.0');
    const { container } = renderCard('18.0.0');
    expect(container.textContent).toBe('');
  });

  it('stays closed through a patch release', () => {
    localStorage.setItem(LAST_SEEN_KEY, '18.0.0');
    const { container } = renderCard('18.0.3');
    expect(container.textContent).toBe('');
  });

  it('comes back for the next feature release', () => {
    localStorage.setItem(LAST_SEEN_KEY, '18.0.0');
    renderCard('18.1.0');
    expect(cardRegion()).not.toBeNull();
  });

  it('reads an acknowledged version written with a leading v', () => {
    localStorage.setItem(LAST_SEEN_KEY, 'v18.0.0');
    const { container } = renderCard('18.0.0');
    expect(container.textContent).toBe('');
  });

  it('is not closed by the update card key, which is a different notice', () => {
    localStorage.setItem('oe_update_dismissed_version', '18.0.0');
    renderCard('18.0.0');
    expect(cardRegion()).not.toBeNull();
  });
});
