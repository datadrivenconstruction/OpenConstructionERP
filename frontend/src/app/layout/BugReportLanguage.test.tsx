// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the bug menu hands to GitHub is written in English, whatever language
 * the app is running in.
 *
 * A report filed from /modules on 16.8.0 arrived titled in Spanish, and its
 * "last error" section said, also in Spanish, that no error had been captured.
 * Neither sentence was typed by anyone: both were locale values interpolated
 * into the payload, so the same automatic report could arrive in any of the
 * languages we ship. A title in forty odd spellings cannot be scanned down an
 * issue list, cannot be searched for a duplicate, and does not tell a reader
 * who does not speak it whether an error was attached at all.
 *
 * The mechanism was the translator being in reach of the payload, so that is
 * what these tests deny. `react-i18next` is mocked locally to answer every
 * key with a marked, non-English string - the whole UI is "translated", not
 * only the two keys that leaked - and the payload is then required to carry
 * none of it. A test that Spanish-ified only the keys we know about would go
 * green the day a third one is added.
 *
 * The global mock in `src/test/setup.ts` returns each `defaultValue`, which
 * reads in English. Under it a payload built through `t()` looks correct, so
 * asserting English against that mock proves nothing at all: it would pass on
 * the build that filed the Spanish report.
 *
 * The reporter's own words are the opposite case and get the opposite
 * assertion. They are the report, they are data, and they travel exactly as
 * typed - a scrubber that anglicised them would be a worse defect than the
 * one being fixed here.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type React from 'react';

const openLink = vi.hoisted(() => vi.fn());

// Keep the real module; observe only the call that hands the report off.
vi.mock('@/shared/lib/desktop', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/desktop')>();
  return { ...actual, openLink };
});

/**
 * Every string the UI can translate comes back marked and non-English.
 * Anything bearing this token in the outgoing report reached it through a
 * locale bundle, which is precisely what must not happen.
 *
 * Hoisted with the mock that uses it: `vi.mock` runs before the module body,
 * so a plain const here would be read before it is initialised.
 */
const { TRANSLATED } = vi.hoisted(() => ({ TRANSLATED: 'traduccion-de-la-interfaz' }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => `${TRANSLATED}:${key}`,
    i18n: { language: 'es', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import { BugReportMenu, MIN_DESCRIPTION_LENGTH } from './Header';

/** What a Spanish-speaking reporter would have written into the field. */
const REPORTER_WORDS =
  'Pulse Instalar en un modulo y la pagina se quedo vacia, sin ningun mensaje.';

/**
 * The popover's controls are located by role and position rather than by
 * label, because in these tests no label is in English. The channels are the
 * only buttons inside the dialog and keep their declared order, so the first
 * is the one that opens GitHub.
 */
function openMenuOnModules(lang: string | null) {
  window.history.pushState({}, '', '/modules');
  // `null` leaves the attribute as the document found it, which is how the
  // page looks if App.tsx ever stops setting it.
  if (lang !== null) document.documentElement.lang = lang;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BugReportMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getAllByRole('button')[0]!);
  const dialog = screen.getByRole('dialog');
  return {
    github: within(dialog).getAllByRole('button')[0] as HTMLButtonElement,
    description: within(dialog).getByRole('textbox') as HTMLTextAreaElement,
  };
}

/** File a report and return the GitHub URL the menu opened. */
function fileReport(lang: string | null = 'es'): URL {
  const { github, description } = openMenuOnModules(lang);
  fireEvent.change(description, { target: { value: REPORTER_WORDS } });
  expect(REPORTER_WORDS.length).toBeGreaterThanOrEqual(MIN_DESCRIPTION_LENGTH);
  fireEvent.click(github);
  expect(openLink).toHaveBeenCalledTimes(1);
  return new URL(openLink.mock.calls[0]![0] as string);
}

beforeEach(() => {
  openLink.mockClear();
  document.documentElement.lang = '';
});

describe('bug report payload - written in English from a UI that is not', () => {
  it('titles the issue in English and names the screen it came from', () => {
    const title = fileReport().searchParams.get('title') ?? '';

    // The exact line that arrived in Spanish, and the surface it names.
    expect(title).toBe('[Modules] Bug report from in-app menu');
    expect(title).not.toContain(TRANSLATED);
  });

  it('says in English that a quiet session captured no error', () => {
    const body = fileReport().searchParams.get('body') ?? '';

    // A session with nothing wrong in it is the case that produced the
    // report this test exists for: the marker is all a reader gets, so it
    // has to be a marker they can read.
    expect(body).toContain('_No error captured during this session._');
    expect(body).not.toContain(TRANSLATED);
  });

  it('keeps the scaffolding of the body English', () => {
    const body = fileReport().searchParams.get('body') ?? '';

    expect(body).toContain('### Description');
    expect(body).toContain('### Environment');
    expect(body).toContain('### Last error captured');
    expect(body).toContain('- Component: Modules');
  });

  it('sends the reporter own words untouched, in their own language', () => {
    const body = fileReport().searchParams.get('body') ?? '';

    // Not translated, not scrubbed, not summarised. This is the half of the
    // payload that is data rather than ours to word.
    expect(body).toContain(REPORTER_WORDS);
  });

  it('records the language the app was running in', () => {
    const body = fileReport().searchParams.get('body') ?? '';

    // Absent from the report that prompted this, and the reason its language
    // had to be inferred from the reporter prose rather than read off a line.
    expect(body).toContain('- UI locale: es');
  });

  it('names some language even when the document attribute is unset', () => {
    // The attribute belongs to App.tsx. If it ever stops being set, the line
    // has to fall back to the browser locale rather than emit an empty value,
    // which would read as though the question had not been asked.
    const body = fileReport(null).searchParams.get('body') ?? '';

    expect(body).toMatch(/- UI locale: \S+/);
    expect(body).not.toContain('- UI locale: unknown');
  });
});
