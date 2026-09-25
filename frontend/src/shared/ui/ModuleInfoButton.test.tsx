// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Feature test for the collapse -> re-open flow of a module info block.
//
// Founder 2026-08-07: a collapsed block folds into an information icon beside
// the module name, and re-opens from there. The choice is saved per-user
// (localStorage now, server on the next boot). These tests drive the real
// DismissibleInfo + ModuleInfoButton pair (they talk through the real
// useModuleInfoStore registry and the real useInfoBlockPrefsStore) and assert:
//
//   1. Block starts expanded; no re-open icon.
//   2. Collapsing hides the block and shows the icon; the choice lands in the
//      per-user store + its localStorage bucket and is pushed to the server.
//   3. The icon re-opens the block and clears the collapsed flag.
//   4. A legacy per-browser `oce.intro.<key>` flag still collapses the block
//      once, so preferences set before this change carry over.
//   5. The control is icon-only but keeps an accessible name, because it now
//      shares the top bar with the module name.
//   6. One click restores BOTH kinds of block when a page carries both.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

/* ── i18n shim — return the defaultValue verbatim. ─────────────────────── */
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}));

/* ── api shim — the prefs store syncs through these; keep them off-network. */
const apiMocks = vi.hoisted(() => ({ apiGet: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', () => ({
  apiGet: apiMocks.apiGet,
  apiPut: apiMocks.apiPut,
}));

import { CollapsibleSection } from './CollapsibleSection';
import { DismissibleInfo } from './DismissibleInfo';
import { ModuleInfoButton } from './ModuleInfoButton';
import { useInfoBlockPrefsStore } from '@/stores/useInfoBlockPrefsStore';
import { useModuleInfoStore } from '@/stores/useModuleInfoStore';

function Harness({ storageKey }: { storageKey: string }) {
  return (
    <>
      <ModuleInfoButton />
      <DismissibleInfo storageKey={storageKey} title="Test card">
        Body copy
      </DismissibleInfo>
    </>
  );
}

beforeEach(() => {
  localStorage.clear();
  apiMocks.apiGet.mockResolvedValue({ blocks: {} });
  apiMocks.apiPut.mockResolvedValue({ blocks: {} });
  apiMocks.apiPut.mockClear();
  // Reset the two singleton stores between tests.
  useInfoBlockPrefsStore.setState({ blocks: {}, hydrated: false });
  useModuleInfoStore.setState({ entries: [] });
});

afterEach(() => {
  cleanup();
});

describe('module info card collapse / re-open', () => {
  it('starts expanded with no re-open icon', () => {
    render(<Harness storageKey="ib-a" />);
    expect(screen.getByText('Test card')).toBeTruthy();
    expect(screen.queryByTestId('module-info-button')).toBeNull();
  });

  it('collapses into the icon and re-opens from it', () => {
    render(<Harness storageKey="ib-b" />);

    // Collapse via the card title (a dedicated toggle button).
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));

    // Card is gone from the flow; the re-open icon appears.
    expect(screen.queryByText('Test card')).toBeNull();
    const icon = screen.getByTestId('module-info-button');
    expect(icon).toBeTruthy();
    expect(useInfoBlockPrefsStore.getState().blocks['ib-b']).toBe(true);

    // Re-open from the icon.
    fireEvent.click(icon);
    expect(screen.getByText('Test card')).toBeTruthy();
    expect(useInfoBlockPrefsStore.getState().blocks['ib-b']).toBe(false);
    expect(screen.queryByTestId('module-info-button')).toBeNull();
  });

  it('persists the collapse to the per-user store and pushes it to the server', async () => {
    render(<Harness storageKey="ib-sync" />);
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));

    // localStorage bucket (instant offline) holds the flag.
    const bucket = JSON.parse(localStorage.getItem('oce.info-blocks') || '{}');
    expect(bucket?.state?.blocks?.['ib-sync']).toBe(true);

    // Debounced write-through reaches the server endpoint.
    await waitFor(() =>
      expect(apiMocks.apiPut).toHaveBeenCalledWith(
        '/v1/users/me/info-blocks/',
        expect.objectContaining({ blocks: expect.objectContaining({ 'ib-sync': true }) }),
      ),
    );
  });

  it('honours a legacy oce.intro.<key> flag as a one-time fallback', () => {
    localStorage.setItem('oce.intro.ib-legacy', '1');
    render(<Harness storageKey="ib-legacy" />);

    // Collapsed on first render from the legacy flag, icon available.
    expect(screen.queryByText('Test card')).toBeNull();
    expect(screen.getByTestId('module-info-button')).toBeTruthy();
  });

  it('carries a name without spending a word of the top bar on it', () => {
    render(<Harness storageKey="ib-name" />);
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));

    const icon = screen.getByTestId('module-info-button');
    // The control sits beside the module name in a bar already holding the
    // project switcher, the search box and the action cluster. A visible
    // label there pushes the module name into truncation at lg widths, which
    // is why this is icon-only - and why the name has to come from aria.
    expect(icon.textContent).toBe('');
    expect(icon.getAttribute('aria-label')).toBe('Module information');
  });

  it('restores a card and an explainer collapsed on the same page in one click', () => {
    render(
      <>
        <ModuleInfoButton />
        <DismissibleInfo storageKey="ib-both" title="Test card">
          Body copy
        </DismissibleInfo>
        <CollapsibleSection storageKey="ib-both" title="Test explainer">
          Explainer body
        </CollapsibleSection>
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    fireEvent.click(screen.getByText('Test explainer'));
    expect(screen.queryByText('Test card')).toBeNull();
    expect(screen.queryByText('Test explainer')).toBeNull();

    // Both blocks are registered under the SAME storageKey here on purpose:
    // the store namespaces an explainer as `section:<key>`, and without that
    // prefix one block would overwrite the other's entry and only one of the
    // two would ever come back. One control, one click, both blocks.
    fireEvent.click(screen.getByTestId('module-info-button'));
    expect(screen.getByText('Test card')).toBeTruthy();
    expect(screen.getByText('Test explainer')).toBeTruthy();
  });
});
