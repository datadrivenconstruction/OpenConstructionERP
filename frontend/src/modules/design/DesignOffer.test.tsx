import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';
import { CONSENT_KEY, resetLoadState } from './data/webEditor';

const store = vi.hoisted(() => ({ enabled: {} as Record<string, boolean>, set: vi.fn() }));
const load = vi.hoisted(() => vi.fn((_c?: string) => null));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useModuleStore', () => ({
  useModuleStore: (sel: (s: { enabledModules: Record<string, boolean>; setModuleEnabled: typeof store.set }) => unknown) =>
    sel({ enabledModules: store.enabled, setModuleEnabled: store.set }),
}));
vi.mock('./editorPayload', () => ({ startBackgroundLoad: load, currentPayload: vi.fn() }));

import { DesignOffer } from './DesignOffer';

async function mount(variant: 'tour' | 'empty' | 'drawings') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({ lng: 'en', resources: { en: { translation: EN } }, keySeparator: false, nsSeparator: false });
  render(<MemoryRouter><I18nextProvider i18n={inst}><DesignOffer variant={variant} /></I18nextProvider></MemoryRouter>);
  return userEvent.setup();
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  load.mockClear();
  store.set.mockClear();
  resetLoadState();
});

describe('background load is decided at the design offer', () => {
  it('yes at set-up: module on, consent stored, load scheduled for idle time', async () => {
    const user = await mount('tour');
    await user.click(screen.getByRole('button', { name: EN['design.offer.yes'] }));
    expect(store.set).toHaveBeenCalledWith('design', true);
    expect(localStorage.getItem(CONSENT_KEY)).toBe('yes');
    expect(load).toHaveBeenCalledWith('yes');
  });

  it('drawing uploads (DWG/PDF) get the offer with its own wording and yes works the same', async () => {
    const user = await mount('drawings');
    expect(screen.getByTestId('design-offer-drawings').textContent).toContain(EN['design.offer.drawings']);
    await user.click(screen.getByRole('button', { name: EN['design.offer.enable'] }));
    expect(store.set).toHaveBeenCalledWith('design', true);
  });

  it('yes on the model page hero counts the same', async () => {
    const user = await mount('empty');
    await user.click(screen.getByRole('button', { name: EN['design.offer.enable'] }));
    expect(localStorage.getItem(CONSENT_KEY)).toBe('yes');
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('not now: nothing is loaded and the answer is kept', async () => {
    const user = await mount('tour');
    await user.click(screen.getByRole('button', { name: EN['design.offer.later'] }));
    expect(localStorage.getItem(CONSENT_KEY)).toBe('no');
    expect(load).not.toHaveBeenCalled();
  });
});
