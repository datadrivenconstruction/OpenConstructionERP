// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The half of the relative-timestamp guard that a mock cannot fake.
//
// `dateFnsLocale.test.ts` proves the map answers German for `de`. This proves
// the component actually asks it: drop `locale` from the `formatDistanceToNow`
// call and date-fns keeps returning a perfectly valid string, in English, with
// nothing red anywhere. The assertion is therefore on the rendered words, and
// it is written in both directions, because "contains vor" alone would still
// pass on a string that also carried the English.
//
// Run:  npx vitest run src/shared/ui/DateDisplay.relativeLocale.test.tsx

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';
import i18next from 'i18next';

import { DateDisplay } from './DateDisplay';

const FIXED_NOW = new Date('2026-05-25T12:00:00Z');
const THREE_HOURS_EARLIER = '2026-05-25T09:00:00Z';

beforeAll(async () => {
  // The harness stubs `react-i18next`, not `i18next` itself, and the real
  // instance is what `getDateFnsLocale` reads. Without this it is
  // uninitialised, `language` is undefined, and every case below would pass
  // for the wrong reason by falling back to English.
  if (!i18next.isInitialized) {
    await i18next.init({ lng: 'en', resources: { en: { translation: {} } } });
  }
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
});

afterEach(async () => {
  vi.useRealTimers();
  await i18next.changeLanguage('en');
});

describe('<DateDisplay format="relative">', () => {
  it('renders German for a German reader', async () => {
    await i18next.changeLanguage('de');
    const { container } = render(<DateDisplay value={THREE_HOURS_EARLIER} format="relative" />);
    const text = container.textContent ?? '';
    expect(text).toContain('vor');
    expect(text).toContain('Stunden');
    expect(text).not.toContain('ago');
    expect(text).not.toContain('hours');
  });

  it('renders Russian for a Russian reader', async () => {
    await i18next.changeLanguage('ru');
    const { container } = render(<DateDisplay value={THREE_HOURS_EARLIER} format="relative" />);
    const text = container.textContent ?? '';
    // Cyrillic here is the value under test, not a hardcoded UI string.
    expect(text).toContain('назад');
    expect(text).not.toContain('ago');
  });

  it('still renders English for an English reader', async () => {
    await i18next.changeLanguage('en');
    const { container } = render(<DateDisplay value={THREE_HOURS_EARLIER} format="relative" />);
    expect(container.textContent ?? '').toContain('ago');
  });

  it('gives three different languages three different answers', async () => {
    // Two sets that come back equal would be the finding. Before the fix all
    // three of these were the same string, which is the signature that told us
    // the locale was missing rather than the translation.
    const rendered: string[] = [];
    for (const lang of ['en', 'de', 'ja']) {
      await i18next.changeLanguage(lang);
      const { container } = render(<DateDisplay value={THREE_HOURS_EARLIER} format="relative" />);
      rendered.push(container.textContent ?? '');
    }
    expect(new Set(rendered).size).toBe(3);
  });
});
