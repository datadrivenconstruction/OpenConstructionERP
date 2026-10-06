// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// When a reader switches language, the text they can SEE changes. This file is
// about the text they cannot see: the accessible name of the chat dialog.
//
// `FloatingChatPanel` names its `role="dialog"` container with `aria-label`.
// That name is the only thing a screen reader announces when the dialog opens,
// and it was seeded once into component state at mount:
//
//     const [title, setTitle] = useState(t('chat.panel.title_default'))
//     const panelTitle = useMemo(() => title, [title])
//     <div role="dialog" aria-label={panelTitle}>
//
// A `useState` initialiser runs on the first render and never again, so the
// name kept whatever language the panel happened to mount in. A reader who
// switched to German got a panel whose visible chrome was German and whose
// dialog still announced itself in English. Nothing on screen showed it.
//
// Why a test that renders once cannot catch this: the attribute is CORRECT on
// a fresh mount in any language. Mount in German and it says German. The
// defect only exists in the gap between two languages, so the test has to
// switch and re-read the same node.
//
// The trap in writing that test is that a component which fails to re-render
// AT ALL looks exactly like a stale memo - both hand back the old string. So
// every assertion here is paired with a control read from the SAME render
// pass: the `aria-label` on the title input two lines below, which has always
// called `t()` inline. If the control moves and the subject does not, the
// component re-rendered and the subject is stale. If neither moves, the
// harness is broken and the test says so instead of blaming the code.
//
// The harness needs one thing said out loud. `src/test/setup.ts` mocks
// `react-i18next` for the whole suite, and in that mock `i18n.language` is the
// constant 'en' and `changeLanguage` is `vi.fn()` - a no-op. Under it, a
// language switch cannot change anything, so a language test written the
// obvious way passes against broken and fixed code alike. This suite unmocks
// it and drives a real i18next instance.
//
// Run:  npx vitest run src/features/erp-chat/__tests__/attributesFollowTheLanguage.test.tsx

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';

// This suite exercises the real i18next wiring, so the harness-wide mock of
// react-i18next (src/test/setup.ts) must not stand in for it here.
vi.unmock('react-i18next');

// The renderer registry maps every backend renderer name to a card component
// (charts, grids, viewers). An attribute assertion never reaches one, and
// loading the set costs more than the rest of this file put together. The two
// network calls are stubbed so the panel settles instead of retrying.
vi.mock('../full-page/right/renderers', () => ({ RENDERER_REGISTRY: {} }));
vi.mock('../api', () => ({ fetchChatSessions: () => Promise.resolve([]) }));
vi.mock('@/features/ai/api', () => ({ aiApi: { getSettings: () => Promise.resolve({ ai_ready: true }) } }));
vi.mock('@/features/ai-estimator/useAiReadiness', () => ({ hasLlmKey: () => true }));

// Two fixture languages that disagree on every key. Asserting against real
// shipped strings would pin today's wording; asserting that the value CHANGED
// pins the property that was broken.
const EN = {
  'chat.panel.title_default': 'AI assistant',
  'chat.panel.title_edit': 'Conversation title',
};
const DE = {
  'chat.panel.title_default': 'KI-Assistent',
  'chat.panel.title_edit': 'Gespraechstitel',
};

type PanelModule = typeof import('../FloatingChatPanel');
let FloatingChatPanel: PanelModule['FloatingChatPanel'];
let useFloatingChatStore: typeof import('../useFloatingChat')['useFloatingChatStore'];

beforeAll(async () => {
  await i18next.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: EN }, de: { translation: DE } },
    interpolation: { escapeValue: false },
    initAsync: false,
  });
  // jsdom has no matchMedia; the panel asks it whether the viewport is mobile.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
  ({ FloatingChatPanel } = await import('../FloatingChatPanel'));
  ({ useFloatingChatStore } = await import('../useFloatingChat'));
});

afterEach(() => {
  cleanup();
});

afterAll(async () => {
  await i18next.changeLanguage('en');
});

/** Mount the panel open, in `lng`, and hand back a reader for its attributes. */
async function mountPanel(lng: string) {
  await act(async () => {
    await i18next.changeLanguage(lng);
  });
  useFloatingChatStore.setState({ isOpen: true, activeSessionId: null, pendingPrompt: null });

  const view = render(
    <MemoryRouter>
      <FloatingChatPanel />
    </MemoryRouter>,
  );
  // Let the stubbed settings/session promises land inside act(), so their
  // state updates belong to this render rather than warning into the next one.
  await act(async () => {
    await Promise.resolve();
  });

  const dialog = () => view.container.querySelector('[role="dialog"]');
  return {
    view,
    /** SUBJECT: the accessible name of the dialog - what a screen reader says. */
    dialogName: () => dialog()?.getAttribute('aria-label') ?? null,
    /**
     * CONTROL: an aria-label on the same render pass that has always called
     * `t()` inline. It moving proves the component re-rendered.
     */
    controlName: () => {
      const inputs = Array.from(dialog()?.querySelectorAll('input[aria-label]') ?? []);
      return inputs[0]?.getAttribute('aria-label') ?? null;
    },
    switchTo: async (next: string) => {
      await act(async () => {
        await i18next.changeLanguage(next);
      });
    },
  };
}

describe('the chat dialog announces itself in the reader language', () => {
  it('renders an accessible name at all, in the language it mounted in', async () => {
    const panel = await mountPanel('en');
    // Without this the rest of the file could pass by comparing null to null.
    expect(panel.dialogName()).toBe(EN['chat.panel.title_default']);
    expect(panel.controlName()).toBe(EN['chat.panel.title_edit']);
  });

  it('is correct on a fresh mount in German, which is why one render cannot catch the bug', async () => {
    const panel = await mountPanel('de');
    expect(panel.dialogName()).toBe(DE['chat.panel.title_default']);
  });

  it('follows a language switch after mount', async () => {
    const panel = await mountPanel('en');
    const beforeSubject = panel.dialogName();
    const beforeControl = panel.controlName();
    expect(beforeSubject).toBe(EN['chat.panel.title_default']);

    await panel.switchTo('de');

    // Control first: if the inline-t() label did not move either, the panel
    // never re-rendered and this run says nothing about the subject.
    expect(panel.controlName()).not.toBe(beforeControl);
    expect(panel.controlName()).toBe(DE['chat.panel.title_edit']);

    // Subject: the dialog's accessible name must have followed too.
    expect(panel.dialogName()).not.toBe(beforeSubject);
    expect(panel.dialogName()).toBe(DE['chat.panel.title_default']);
  });

  it('switches back, so the first direction was not a one-way reset', async () => {
    const panel = await mountPanel('de');
    expect(panel.dialogName()).toBe(DE['chat.panel.title_default']);
    await panel.switchTo('en');
    expect(panel.dialogName()).toBe(EN['chat.panel.title_default']);
  });

  // The panel title is editable - the user renames the conversation in the
  // header input. Re-deriving the name from `t()` on every render would be a
  // fix that silently throws that rename away on the next language switch, so
  // the rename is pinned here as the constraint the fix has to respect.
  it('leaves a conversation the user renamed alone when the language changes', async () => {
    const panel = await mountPanel('en');
    const input = panel.view.container.querySelector(
      '[role="dialog"] input[aria-label]',
    ) as HTMLInputElement | null;
    expect(input).not.toBeNull();

    const RENAMED = 'Q3 tender questions';
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(input, RENAMED);
      input!.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(panel.dialogName()).toBe(RENAMED);

    await panel.switchTo('de');
    // The chrome around it translated; the user's own words did not.
    expect(panel.controlName()).toBe(DE['chat.panel.title_edit']);
    expect(panel.dialogName()).toBe(RENAMED);
    const disclosure = panel.view.getByTestId('chat-ai-disclosure');
    expect(disclosure).toBeVisible();
    expect(disclosure).toHaveTextContent(DE['chat.panel.title_default']);
    expect(panel.view.getByRole('dialog')).toHaveAccessibleDescription(DE['chat.panel.title_default']);
    await panel.switchTo('en');
    expect(disclosure).toHaveTextContent(EN['chat.panel.title_default']);
    expect(panel.dialogName()).toBe(RENAMED);
  });
});
