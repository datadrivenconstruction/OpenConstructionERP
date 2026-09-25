/**
 * Tests for the shared DismissibleInfo help card.
 *
 * Behaviour under test (the 2026-06-06 contract, collapse control narrowed):
 *   - clicking the title or the body does nothing; only the named Collapse
 *     button collapses the card
 *   - collapsing leaves NOTHING in the page; the card
 *     registers itself in useModuleInfoStore so the TOP APP BAR can show the
 *     re-opener icon (project pill > module name > info icon)
 *   - the X ALSO just collapses (it never hides the card forever)
 *   - the store's expand entry re-expands the card and unregisters it
 *   - a legacy localStorage value of "2" (old "dismissed") maps to collapsed
 *   - a stored "1" maps to collapsed
 *   - clicking an inner link pill runs its handler WITHOUT toggling the card
 *   - unmount (navigation) unregisters from the store
 *
 * ``react-i18next`` and ``window.localStorage`` are mocked globally in
 * ``src/test/setup.ts`` (t returns ``defaultValue``; localStorage is an
 * in-memory store with a working ``clear()``).
 *
 * Persistence moved (2026-07-23): collapsing a card is now recorded per USER
 * in ``useInfoBlockPrefsStore`` so the preference follows someone across
 * browsers, and the old per-browser ``oce.intro.<key>`` flag is only READ, as
 * a one-time fallback for cards that store has never seen. Five tests here
 * still asserted a WRITE to the old flag, and to the registry keying by it,
 * so they had been failing against a contract that no longer exists. They now
 * assert the stored preference and the bare storage key; the two legacy cases
 * stay, because reading the old flag is still real behaviour worth pinning.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

import { DismissibleInfo } from './DismissibleInfo';
import { ModuleInfoButton } from './ModuleInfoButton';
import { useModuleInfoStore } from '@/stores/useModuleInfoStore';
import { useInfoBlockPrefsStore } from '@/stores/useInfoBlockPrefsStore';

const KEY = 'demo-card';
/** The LEGACY per-card flag. Still READ once as a fallback for cards the
 *  preferences store has never seen, which is what the two "legacy stored"
 *  tests below cover. It is no longer WRITTEN: collapsing a card now records
 *  the choice per user in `useInfoBlockPrefsStore`, so asserting a write here
 *  would pin behaviour that moved. */
const LEGACY_LS_KEY = `oce.intro.${KEY}`;

/** The collapsed flag as the component actually stores it now. */
function storedCollapsed(key = KEY): boolean | undefined {
  return useInfoBlockPrefsStore.getState().blocks[key];
}

function renderCard(props?: { links?: { label: string; onClick: () => void }[] }) {
  return render(
    <DismissibleInfo storageKey={KEY} title="Demo title" links={props?.links}>
      <span>Body copy explaining the page.</span>
    </DismissibleInfo>,
  );
}

/** The store registry of collapsed cards (what the Header icon reads). */
function storeEntries() {
  return useModuleInfoStore.getState().entries;
}

/** The row that used to carry a whole-card collapse handler. */
function cardClickSurface(): HTMLElement {
  const wrapper = document.querySelector('div.border-l-oe-blue\\/70') as HTMLElement | null;
  if (!wrapper) throw new Error('no expanded card wrapper rendered');
  // First element child is the flex row under the wrapper.
  return wrapper.firstElementChild as HTMLElement;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  useModuleInfoStore.setState({ entries: [] });
  // The preferences store is module-level and survives between tests, so a
  // collapse in one case would otherwise decide the next case's initial state.
  useInfoBlockPrefsStore.setState({ blocks: {} });
});

describe('DismissibleInfo', () => {
  it('renders expanded by default with title, body and an expanded toggle', () => {
    renderCard();
    expect(screen.getByText('Demo title')).toBeInTheDocument();
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
    // A toggle marked aria-expanded carries the collapse semantics for AT.
    expect(document.querySelector('[aria-expanded="true"]')).toBeInTheDocument();
    // Nothing registered while expanded - the top bar shows no icon.
    expect(storeEntries()).toHaveLength(0);
  });

  it('clicking the title or the body leaves the card expanded', () => {
    renderCard();
    // The title used to be a button that collapsed the card, and the whole
    // row carried the same handler, so any click on the card lost it.
    fireEvent.click(screen.getByText('Demo title'));
    fireEvent.click(screen.getByText('Body copy explaining the page.'));
    fireEvent.click(cardClickSurface());

    expect(screen.getByText('Demo title')).toBeInTheDocument();
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
    expect(storedCollapsed()).toBeUndefined();
    expect(storeEntries()).toHaveLength(0);
    // The title is text, not a control: the X is the only button.
    expect(screen.queryByRole('button', { name: 'Demo title' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('the named Collapse button collapses it to NOTHING in the page', () => {
    const { container } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));

    // The card leaves the page entirely - no leftover line (founder decision
    // 2026-06-06: the re-opener lives in the top app bar instead).
    expect(screen.queryByText('Body copy explaining the page.')).not.toBeInTheDocument();
    expect(screen.queryByText('Demo title')).not.toBeInTheDocument();
    expect(container.firstChild).toBeNull();
    // Collapsed state recorded per user, not under the legacy per-card flag.
    expect(storedCollapsed()).toBe(true);
    // Registered for the top-bar icon, under the bare storage key.
    expect(storeEntries()).toHaveLength(1);
    expect(storeEntries()[0]!.key).toBe(KEY);
  });

  it('a collapsed card comes back with a click on the module info button', () => {
    render(
      <>
        <ModuleInfoButton />
        <DismissibleInfo storageKey={KEY} title="Demo title">
          <span>Body copy explaining the page.</span>
        </DismissibleInfo>
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(screen.queryByText('Demo title')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Module information' }));

    expect(screen.getByText('Demo title')).toBeInTheDocument();
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
    expect(storedCollapsed()).toBe(false);
    // Nothing collapsed any more, so the re-open control leaves the bar.
    expect(screen.queryByRole('button', { name: 'Module information' })).not.toBeInTheDocument();
  });

  it('the store expand entry (top-bar icon) re-expands and persists "0"', () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(storeEntries()).toHaveLength(1);

    // The Header icon calls expandAll(), which fires the registered expand.
    act(() => useModuleInfoStore.getState().expandAll());

    expect(screen.getByText('Demo title')).toBeInTheDocument();
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
    expect(storedCollapsed()).toBe(false);
    // Expanded card unregisters - the top-bar icon disappears.
    expect(storeEntries()).toHaveLength(0);
  });

  it('the X collapses the card (it never hides it forever) and persists "1"', () => {
    const { unmount } = renderCard();
    const collapseBtn = screen.getByRole('button', { name: /collapse/i });
    fireEvent.click(collapseBtn);

    // Gone from the page, registered for the top bar.
    expect(screen.queryByText('Body copy explaining the page.')).not.toBeInTheDocument();
    expect(storedCollapsed()).toBe(true);
    expect(storeEntries()).toHaveLength(1);

    // Remount with the SAME storageKey -> still collapsed, still registered.
    unmount();
    expect(storeEntries()).toHaveLength(0); // unmount unregistered
    renderCard();
    expect(screen.queryByText('Demo title')).not.toBeInTheDocument();
    expect(storeEntries()).toHaveLength(1);
  });

  it('legacy stored "1" maps to collapsed (nothing in page, registered)', () => {
    window.localStorage.setItem(LEGACY_LS_KEY, '1');
    const { container } = renderCard();

    expect(container.firstChild).toBeNull();
    expect(storeEntries()).toHaveLength(1);
  });

  it('legacy stored "2" (old "dismissed") maps to collapsed and stays reachable', () => {
    window.localStorage.setItem(LEGACY_LS_KEY, '2');
    const { container } = renderCard();

    // No longer hidden forever: registered, so the top-bar icon re-opens it.
    expect(container.firstChild).toBeNull();
    expect(storeEntries()).toHaveLength(1);
    act(() => useModuleInfoStore.getState().expandAll());
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
  });

  it('unmount while collapsed unregisters from the store (navigation)', () => {
    window.localStorage.setItem(LEGACY_LS_KEY, '1');
    const { unmount } = renderCard();
    expect(storeEntries()).toHaveLength(1);
    unmount();
    expect(storeEntries()).toHaveLength(0);
  });

  it('clicking an inner link pill runs its handler WITHOUT toggling the card', () => {
    const onClick = vi.fn();
    renderCard({ links: [{ label: 'Open BOQ', onClick }] });

    const pill = screen.getByRole('button', { name: 'Open BOQ' });
    fireEvent.click(pill);

    // Handler fired, but the card stayed expanded (body still visible) and
    // nothing was persisted (still no toggle write).
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Body copy explaining the page.')).toBeInTheDocument();
    expect(storedCollapsed()).toBeUndefined();
    expect(storeEntries()).toHaveLength(0);
  });

  it('two cards with different keys keep independent state and registrations', () => {
    render(
      <>
        <DismissibleInfo storageKey="a" title="Card A" />
        <DismissibleInfo storageKey="b" title="Card B" />
      </>,
    );
    // Collapse only card A via its X (collapse) button.
    const collapseButtons = screen.getAllByRole('button', { name: /collapse/i });
    expect(collapseButtons).toHaveLength(2);
    fireEvent.click(collapseButtons[0]!);

    // Card A gone from the page and registered; Card B still expanded.
    expect(screen.queryByText('Card A')).not.toBeInTheDocument();
    expect(screen.getByText('Card B')).toBeInTheDocument();
    expect(storedCollapsed('a')).toBe(true);
    expect(storedCollapsed('b')).toBeUndefined();
    expect(storeEntries()).toHaveLength(1);
    expect(storeEntries()[0]!.key).toBe('a');
  });
});
