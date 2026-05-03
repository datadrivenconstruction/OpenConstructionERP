// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Axe-core accessibility check for TranslationSettingsTab.  We render the
 * tab in two meaningful states:
 *   - empty (no dictionaries, no tasks) — the most common first view
 *   - populated (cache rows, downloaded dicts, in-flight task) — the
 *     state with the highest a11y surface area (table, progressbar)
 *
 * Plus a Tab-key keyboard-nav assertion: every interactive form field
 * should be reachable in DOM order.  We do not ``act()`` between
 * keypresses because we only inspect the document; jsdom's focus model
 * matches the resolved tabindex closely enough for this smoke check.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getTranslationStatus: vi.fn(),
    triggerLookupDownload: vi.fn(),
    translateOne: vi.fn(),
  };
});

// The component reads the toast store via
// ``useToastStore((s) => s.addToast)``, so the mock must behave like a
// Zustand hook (callable as a selector + ``getState``).  Hoisted so it's
// resolvable from inside the hoisted ``vi.mock`` factory.
vi.mock('@/stores/useToastStore', () => {
  const toastState = { addToast: vi.fn() };
  const useToastStore = Object.assign(
    (selector?: (s: typeof toastState) => unknown) =>
      typeof selector === 'function' ? selector(toastState) : toastState,
    { getState: () => toastState },
  );
  return { useToastStore };
});

import { getTranslationStatus } from '../api';
import { TranslationSettingsTab } from '../TranslationSettingsTab';

expect.extend(toHaveNoViolations);

function renderTab() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <TranslationSettingsTab projectId="proj-1" />
    </QueryClientProvider>,
  );
}

describe('TranslationSettingsTab — a11y', () => {
  beforeEach(() => {
    vi.mocked(getTranslationStatus).mockReset();
  });

  it('has no axe violations in the empty state', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue({
      dictionaries: { muse: [], iate: [] },
      cache: { rows: 0, hits: 0 },
      in_flight: [],
    });

    const { container, findByTestId } = renderTab();
    await findByTestId('translation-dict-empty');

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations in the populated state', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue({
      dictionaries: {
        muse: [
          {
            pair: 'en-de',
            path: '/x/muse/en-de.tsv',
            size_bytes: 4_500_000,
            modified_at: Math.floor(Date.now() / 1000) - 3600,
          },
        ],
        iate: [],
      },
      cache: { rows: 12, hits: 5 },
      in_flight: [
        {
          task_id: 'abc',
          kind: 'muse',
          status: 'running',
          progress: 0.6,
        },
      ],
    });

    const { container, findByTestId } = renderTab();
    await findByTestId('translation-task-abc');

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('keeps every interactive form field reachable via Tab (DOM order)', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue({
      dictionaries: { muse: [], iate: [] },
      cache: { rows: 0, hits: 0 },
      in_flight: [],
    });

    const { findByTestId, container } = renderTab();
    await findByTestId('translation-muse-form');

    // Collect every focusable element in DOM order.  All of them should
    // have a sane (non-negative or unset) tabindex so a real Tab keypress
    // walks them one-by-one.
    const focusables = container.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );

    expect(focusables.length).toBeGreaterThan(0);
    for (const el of Array.from(focusables)) {
      const tabIndex = el.getAttribute('tabindex');
      if (tabIndex !== null) {
        expect(Number(tabIndex)).toBeGreaterThanOrEqual(0);
      }
    }

    // Sanity: programmatic focus on the MUSE select shouldn't throw and
    // should land on the element.  We do not simulate keyboard navigation
    // directly — jsdom's Tab handling is partial — but ``HTMLElement.focus``
    // is reliably implemented.  This rules out display:none / hidden /
    // disabled foot-guns that would break the keyboard trail.
    const firstField = container.querySelector(
      '[data-testid="translation-muse-preset"]',
    ) as HTMLSelectElement | null;
    expect(firstField).toBeTruthy();
    firstField!.focus();
    expect(document.activeElement).toBe(firstField);
  });
});
