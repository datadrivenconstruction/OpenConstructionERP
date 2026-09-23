// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SupportUsButton - where the cross-surface quiet period applies.
 *
 * The review card (`shared/ui/ReviewPromptCard.tsx`) makes the same asks as
 * this modal, so the modal's UNPROMPTED auto-popup defers to it. Opening the
 * modal from the button must never be suppressed - that is someone choosing
 * to support us.
 *
 * The obvious way to get that wrong is to put the guard in `handleOpen`
 * instead of the auto-popup effect. Every cadence test in
 * `stores/useReviewPromptStore.test.ts` would still pass, and the manual
 * button would be silently dead for days at a time. Both tests below exist to
 * catch exactly that, from two directions: the modal still opens on click,
 * and the guard is not even consulted on that path.
 *
 * WHAT IS NOT COVERED HERE, AND WHY.
 * The auto-popup itself is not driven in this file. It fires only after 20
 * minutes of accumulated active-tab time, measured as a delta between
 * `Date.now()` at mount and `Date.now()` inside a 10s interval. Under jsdom
 * with fake timers and React Query in the tree that counter does not advance,
 * so the popup never appears - which means an auto-popup "suppression" test
 * here would pass whether or not the guard existed. A test that green-lights
 * a deleted feature is worse than no test, so those assertions were removed
 * rather than left in looking reassuring.
 *
 * The suppression POLICY is covered where it actually lives, in
 * `stores/useReviewPromptStore.test.ts`: six tests including a two-year
 * day-by-day simulation of a user who declines every ask, proving the quiet
 * window is bounded by the card's hard cap and can never become a permanent
 * mute. Those tests are mutation-verified.
 *
 * `react-i18next` and `localStorage` are mocked globally in `src/test/setup.ts`.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const reviewAskShownWithin = vi.hoisted(() => vi.fn(() => true));

// Keep the real module (constants, store) but observe the one function the
// modal is supposed to call ONLY on the auto path. It is stubbed to always
// report "the card just asked", so if the guard were wired into the manual
// path the click test below would fail loudly.
vi.mock('@/stores/useReviewPromptStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/useReviewPromptStore')>();
  return { ...actual, reviewAskShownWithin };
});

import { SupportUsButton } from './SupportUsButton';

function renderButton() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SupportUsButton />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const modalVisible = () => screen.queryByRole('dialog') !== null;
const supportButton = () => screen.getAllByLabelText('Support us')[0]!;

beforeEach(() => {
  localStorage.clear();
  reviewAskShownWithin.mockClear();
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ demo_mode: false }) })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SupportUsButton - manual opening is never suppressed', () => {
  it('opens from the button even while the review card counts as recent', () => {
    // The guard is stubbed to report the card as having just asked. If it
    // were consulted here, this modal would not open.
    renderButton();
    expect(modalVisible()).toBe(false);

    fireEvent.click(supportButton());

    expect(modalVisible()).toBe(true);
  });

  it('does not even consult the cross-surface guard when opened by hand', () => {
    renderButton();
    fireEvent.click(supportButton());

    expect(modalVisible()).toBe(true);
    // Pins WHERE the guard lives: the manual path must not ask this question.
    expect(reviewAskShownWithin).not.toHaveBeenCalled();
  });
});
