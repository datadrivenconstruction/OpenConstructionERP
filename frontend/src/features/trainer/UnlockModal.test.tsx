// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The unlock celebration dialog: focus, Escape, focus return, buttons, the
// badge variant and reduced motion.

import { useState, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { UnlockModal, type UnlockModalProps } from './UnlockModal';
import { useTrainerUiStore } from './useTrainerUiStore';

const BASE: Omit<UnlockModalProps, 'onClose'> = {
  unlock: {
    lockId: 'bid_management',
    kind: 'module',
    label: 'Bid Management',
    openedByTask: 2,
    tiles: [
      { title: 'Bid packages', text: 'Send the package with your quantities.' },
      { title: 'Bid comparison', text: 'Three bids side by side.' },
    ],
  },
  contentLang: 'en-GB',
  progress: { done: 2, total: 5 },
  rings: { numbers: true, trace: true, explain: false },
  week: { done: 3, goal: 3 },
  next: { n: 3, taskId: 't3-tender', to: '/bid-management/p1' },
  goThere: '/bid-management',
};

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

/** A page with a trigger button, the dialog open until it closes itself. */
function Page({ props, onClose }: { props: Omit<UnlockModalProps, 'onClose'>; onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        trigger
      </button>
      {open && (
        <UnlockModal
          {...props}
          onClose={() => {
            onClose?.();
            setOpen(false);
          }}
        />
      )}
      <Where />
    </>
  );
}

function open(props: Omit<UnlockModalProps, 'onClose'> = BASE, onClose = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/boq/b1']}>
      <Page props={props} onClose={onClose} />
    </MemoryRouter>,
  );
  const trigger = screen.getByRole('button', { name: 'trigger' });
  trigger.focus();
  fireEvent.click(trigger);
  return { trigger, onClose };
}

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  useTrainerUiStore.getState().reset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.style.overflow = '';
});

describe('UnlockModal', () => {
  it('is a modal dialog labelled by a heading that exists, naming what opened', () => {
    open();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const heading = document.getElementById(labelledBy!);
    expect(heading?.tagName).toBe('H1');
    expect(heading).toHaveTextContent('Bid Management');
    expect(heading).toHaveAttribute('lang', 'en-GB');
    expect(screen.getByRole('dialog', { name: 'Bid Management' })).toBe(dialog);
    expect(screen.getByText('New module open')).toBeInTheDocument();
    expect(screen.getByText('2 of 5 verified.')).toBeInTheDocument();
    expect(dialog).toHaveTextContent("This week's goal: 3/3.");
    expect(screen.getByText('Bid packages')).toBeInTheDocument();
  });

  it('renders into document.body and locks the page scroll while open', () => {
    open();
    expect(screen.getByRole('dialog').parentElement?.parentElement).toBe(document.body);
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).toBe('');
  });

  it('starts focus on the main button and keeps Tab inside', () => {
    open();
    const start = screen.getByRole('button', { name: 'Start task 3' });
    expect(start).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('Escape closes it and focus returns to where it was', () => {
    const { trigger, onClose } = open();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it('a click on the backdrop closes it; a click inside does not', () => {
    const { onClose } = open();
    fireEvent.mouseDown(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByTestId('unlock-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('"Start task" closes, goes to the task and opens it in the dock', () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole('button', { name: 'Start task 3' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('where')).toHaveTextContent('/bid-management/p1');
    expect(useTrainerUiStore.getState()).toMatchObject({ dockTaskId: 't3-tender', dockOpen: true });
  });

  it('"Go there" goes to the opened screen when there is no next task', () => {
    open({ ...BASE, next: null });
    fireEvent.click(screen.getByRole('button', { name: 'Go there' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/bid-management');
    expect(useTrainerUiStore.getState().dockTaskId).toBeNull();
  });

  it('"Course map" goes to the course map', () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Course map' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/academy');
  });

  it('a panel unlock says a panel opened', () => {
    open({ ...BASE, unlock: { ...BASE.unlock, kind: 'panel', label: 'Markups' } });
    expect(screen.getByText('New panel open')).toBeInTheDocument();
  });

  it('badge variant: the course is complete, no padlock, and the main button closes', () => {
    const { onClose } = open({
      ...BASE,
      unlock: { lockId: 'badge:fx-quillmere-1', kind: 'badge', label: 'Quillmere Depot', openedByTask: 5, tiles: [] },
      next: null,
      goThere: null,
    });
    expect(screen.getByText('Course complete')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Quillmere Depot');
    expect(screen.queryByTestId('unlock-shackle')).toBeNull();
    expect(screen.queryByRole('button', { name: /Start task/ })).toBeNull();
    const close = screen.getByRole('button', { name: 'Close' });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('where')).toHaveTextContent('/boq/b1');
  });

  it('with motion allowed, the shackle and the content animate', () => {
    stubReducedMotion(false);
    open();
    expect(screen.getByTestId('unlock-shackle').getAttribute('class')).toContain('oe-trainer-shackle--animate');
    expect(document.querySelector('.oe-trainer-rise')).not.toBeNull();
    expect(screen.getByTestId('unlock-icon').className).toContain('oe-trainer-glow');
  });

  it('under reduced motion: no animation class at all, and the shackle is drawn open', () => {
    stubReducedMotion(true);
    open();
    const dialog = screen.getByRole('dialog');
    const animated = dialog.querySelectorAll(
      '.oe-trainer-rise, .oe-trainer-rise-2, .oe-trainer-rise-3, .oe-trainer-glow, .oe-trainer-glow-badge, .oe-trainer-shackle--animate',
    );
    expect(animated).toHaveLength(0);
    const shackle = screen.getByTestId('unlock-shackle').getAttribute('class') ?? '';
    expect(shackle).toContain('oe-trainer-shackle--open');
    expect(shackle).not.toContain('--animate');
  });

  it('no tiles, no tile grid', () => {
    open({ ...BASE, unlock: { ...BASE.unlock, tiles: [] } });
    expect(screen.getByRole('dialog').querySelector('ul')).toBeNull();
  });
});
