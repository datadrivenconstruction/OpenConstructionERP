/**
 * Tests for TranslationManager component.
 *
 * The i18next mock from setup.ts returns `opts.defaultValue` when provided,
 * so `t('key', { defaultValue: 'Foo' })` → 'Foo' in tests.
 * The i18n module is mocked to provide a small set of predictable translation keys.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { TranslationManager, loadCustomTranslations, saveCustomTranslations } from './TranslationManager';

// ── Mock @/app/i18n ──────────────────────────────────────────────────────────

const FAKE_EN_BUNDLE: Record<string, string> = {
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'nav.dashboard': 'Dashboard',
  'nav.settings': 'Settings',
  'boq.title': 'Bill of Quantities',
};

const FAKE_DE_BUNDLE: Record<string, string> = {
  'common.save': 'Speichern',
  'nav.dashboard': 'Dashboard',
};

let mockLanguage = 'en';

vi.mock('@/app/i18n', () => {
  const addResourceBundle = vi.fn();
  return {
    default: {
      get language() {
        return mockLanguage;
      },
      addResourceBundle,
      getResourceBundle: (lang: string, _ns: string) => {
        if (lang === 'en') return FAKE_EN_BUNDLE;
        if (lang === 'de') return FAKE_DE_BUNDLE;
        return {};
      },
    },
  };
});

// Also re-expose i18next mock to control `i18n.language` in useTranslation
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts === 'object' && 'defaultValue' in opts) return opts.defaultValue as string;
      return key;
    },
    i18n: {
      get language() {
        return mockLanguage;
      },
      changeLanguage: vi.fn(),
    },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderComponent() {
  return render(<TranslationManager />);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('TranslationManager', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLanguage = 'en';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── 1. Renders key list ────────────────────────────────────────────────────

  it('renders all translation keys from the English bundle', () => {
    renderComponent();

    // The table body should contain one row per key in the fake bundle
    const body = screen.getByTestId('tm-table-body');
    for (const key of Object.keys(FAKE_EN_BUNDLE)) {
      // Key column renders the key text
      expect(within(body).getByTitle(key)).toBeInTheDocument();
    }
  });

  // ── 2. Search filters keys ─────────────────────────────────────────────────

  it('filters rows when user types in the search input', () => {
    renderComponent();

    const searchInput = screen.getByTestId('tm-search');

    // Type a query that matches only 'nav.*' keys
    fireEvent.change(searchInput, { target: { value: 'nav.' } });

    const body = screen.getByTestId('tm-table-body');
    // nav.dashboard and nav.settings should appear
    expect(within(body).getByTitle('nav.dashboard')).toBeInTheDocument();
    expect(within(body).getByTitle('nav.settings')).toBeInTheDocument();
    // common.save should NOT appear
    expect(within(body).queryByTitle('common.save')).not.toBeInTheDocument();
  });

  // ── 3. Shows stats ─────────────────────────────────────────────────────────

  it('shows correct total keys count in stats', () => {
    renderComponent();

    const totalEl = screen.getByTestId('tm-stat-total');
    expect(totalEl.textContent).toBe(String(Object.keys(FAKE_EN_BUNDLE).length));
  });

  it('shows custom overrides count as 0 initially', () => {
    renderComponent();

    const customEl = screen.getByTestId('tm-stat-custom');
    expect(customEl.textContent).toBe('0');
  });

  // ── 4. Inline editing saves value ─────────────────────────────────────────

  it('can edit a translation value and saves to localStorage', () => {
    renderComponent();

    // Click on the "current language" cell of 'common.save'
    const editCell = screen.getByTestId('tm-edit-cell-common.save');
    fireEvent.click(editCell);

    // Input should appear
    const input = screen
      .getByTestId('tm-table-body')
      .querySelector('input') as HTMLInputElement;
    expect(input).not.toBeNull();

    // Type a new value
    fireEvent.change(input, { target: { value: 'Store' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // localStorage should be updated
    const stored = localStorage.getItem('oe_custom_translations_en');
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!) as Record<string, string>;
    expect(parsed['common.save']).toBe('Store');

    // Custom count should now be 1
    expect(screen.getByTestId('tm-stat-custom').textContent).toBe('1');
  });

  // ── 5. Export button triggers download ────────────────────────────────────

  it('export button creates a download link and clicks it', () => {
    vi.useFakeTimers();
    try {
      renderComponent();

      const createObjectURL = vi.fn(() => 'blob:fake-url');
      const revokeObjectURL = vi.fn();
      Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true });
      Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true });

      // Spy on createElement to capture anchor clicks
      const clickSpy = vi.fn();
      const origCreate = document.createElement.bind(document);
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        const el = origCreate(tag);
        if (tag === 'a') {
          vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(clickSpy);
        }
        return el;
      });

      const exportBtn = screen.getByTestId('tm-export-btn');
      fireEvent.click(exportBtn);

      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(clickSpy).toHaveBeenCalledOnce();
      // triggerDownload() defers cleanup behind a 200ms setTimeout so the
      // anchor isn't yanked out of the DOM before the browser fires the
      // download. Advance fake timers to flush the cleanup.
      vi.advanceTimersByTime(250);
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-url');
    } finally {
      vi.useRealTimers();
    }
  });

  // ── 6. Reset restores default ─────────────────────────────────────────────

  it('reset button removes custom override and updates stats', () => {
    // Pre-seed a custom override
    localStorage.setItem(
      'oe_custom_translations_en',
      JSON.stringify({ 'common.cancel': 'Abort' }),
    );

    renderComponent();

    // Custom count should start at 1
    expect(screen.getByTestId('tm-stat-custom').textContent).toBe('1');

    // The row should show the reset button
    const resetBtn = screen.getByTestId('tm-reset-common.cancel');
    fireEvent.click(resetBtn);

    // Custom count should now be 0
    expect(screen.getByTestId('tm-stat-custom').textContent).toBe('0');

    // localStorage should no longer contain the key
    const stored = localStorage.getItem('oe_custom_translations_en');
    const parsed = stored ? (JSON.parse(stored) as Record<string, string>) : {};
    expect(parsed['common.cancel']).toBeUndefined();
  });

  // ── 7. loadCustomTranslations / saveCustomTranslations helpers ────────────

  it('loadCustomTranslations returns empty object when nothing stored', () => {
    expect(loadCustomTranslations('en')).toEqual({});
  });

  it('saveCustomTranslations persists data and calls i18n.addResourceBundle', async () => {
    const i18nMod = await import('@/app/i18n');
    const addBundle = vi.spyOn(i18nMod.default, 'addResourceBundle');

    saveCustomTranslations('en', { 'common.save': 'Store' });

    expect(loadCustomTranslations('en')).toEqual({ 'common.save': 'Store' });
    expect(addBundle).toHaveBeenCalledWith('en', 'translation', { 'common.save': 'Store' }, true, true);
  });
});
