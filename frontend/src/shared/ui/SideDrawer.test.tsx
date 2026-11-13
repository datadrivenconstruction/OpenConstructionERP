// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for SideDrawer — the shared right-side slide-over used by
// Property Dev (buyers/plots) and CRM (opportunities/leads) detail
// views. Behaviour covered (R6 propdev side-drawer task):
//
//   1. Renders nothing when open=false.
//   2. Portals into document.body (NOT into the test root).
//   3. role="dialog" and aria-modal="true" set on the panel.
//   4. aria-labelledby points at the title heading.
//   5. Initial focus lands on the first focusable element inside.
//   6. Tab cycles inside the panel — last → first.
//   7. Shift+Tab cycles inside the panel — first → last.
//   8. Escape calls onClose.
//   9. Backdrop click calls onClose when backdropCloses=true.
//  10. Backdrop click does NOT close when backdropCloses=false.
//  11. Click inside the panel does NOT call onClose.
//  12. Click on close (X) button calls onClose.
//  13. Focus returns to the triggering element on close.
//  14. Body scroll is locked while open and restored on unmount.
//  15. busy=true blocks Escape and backdrop close paths.
//  16. headerActions slot renders before the X close button.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useState } from 'react';

import { SideDrawer } from './SideDrawer';
import { WideModal } from './WideModal';

// requestAnimationFrame is fired synchronously in tests so the slide-in
// transform settles immediately and we don't have to await frames.
beforeEach(() => {
  document.body.style.overflow = '';
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    cb(0);
    return 0;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
  // jsdom returns offsetParent === null for every element because it
  // does no layout. ``useFocusTrap`` (and most focus-trap libraries)
  // use offsetParent as a visibility hint to filter out hidden controls,
  // which means the trap sees ZERO focusables under jsdom and the Tab
  // wrap logic short-circuits. Patch HTMLElement.prototype to return a
  // truthy ancestor whenever the element is in the document — that
  // matches a real browser's behaviour for any rendered control.
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement;
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.style.overflow = '';
});

function renderDrawer(
  props: Partial<React.ComponentProps<typeof SideDrawer>> = {},
) {
  const onClose = vi.fn();
  const utils = render(
    <SideDrawer
      open={props.open ?? true}
      onClose={onClose}
      title={props.title ?? 'Buyer details'}
      subtitle={props.subtitle}
      busy={props.busy}
      backdropCloses={props.backdropCloses}
      widthClass={props.widthClass}
      headerActions={props.headerActions}
    >
      {props.children ?? (
        <div data-testid="drawer-body" className="p-5">
          <button type="button" data-testid="first-btn">
            first
          </button>
          <button type="button" data-testid="middle-btn">
            middle
          </button>
          <button type="button" data-testid="last-btn">
            last
          </button>
        </div>
      )}
    </SideDrawer>,
  );
  return { onClose, ...utils };
}

describe('SideDrawer - rendering', () => {
  it('renders nothing when open=false', () => {
    renderDrawer({ open: false });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('portals the panel into document.body', () => {
    const { container } = renderDrawer();
    // The dialog should be attached to document.body, NOT inside the
    // RTL container (which is appended to document.body separately).
    const dialog = screen.getByRole('dialog');
    // The dialog's nearest ancestor with the fixed-positioning wrapper
    // is a direct child of document.body.
    expect(dialog.closest('.fixed')?.parentElement).toBe(document.body);
    // And it is NOT inside the RTL render container.
    expect(container.contains(dialog)).toBe(false);
  });

  it('exposes role=dialog and aria-modal=true', () => {
    renderDrawer();
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
  });

  it('wires aria-labelledby to the title heading', () => {
    renderDrawer({ title: 'My drawer' });
    const dialog = screen.getByRole('dialog');
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const heading = document.getElementById(labelledBy as string);
    expect(heading?.textContent).toBe('My drawer');
  });
});

describe('SideDrawer - focus management', () => {
  it('moves initial focus into a focusable element inside the panel', () => {
    renderDrawer();
    // The first focusable in DOM order is the X close button rendered
    // by the drawer chrome itself. Whatever it is, the active element
    // must live INSIDE the dialog panel — focus must not stay on the
    // page underneath.
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('Tab from the last focusable inside the panel wraps to the first', () => {
    renderDrawer();
    const dialog = screen.getByRole('dialog');
    // Tab cycle: first focusable inside the dialog → … → last → first.
    // Whichever element ends up "last" in DOM order, Tab from it must
    // return focus to the first.
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled])'),
    );
    expect(focusable.length).toBeGreaterThan(1);
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    last.focus();
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
  });

  it('Shift+Tab from the first focusable inside the panel wraps to the last', () => {
    renderDrawer();
    const dialog = screen.getByRole('dialog');
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled])'),
    );
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('returns focus to the triggering element on close', () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button
            type="button"
            data-testid="trigger"
            onClick={() => setOpen(true)}
          >
            open
          </button>
          <SideDrawer open={open} onClose={() => setOpen(false)} title="t">
            <div className="p-2">
              <button type="button" data-testid="inside">
                inside
              </button>
            </div>
          </SideDrawer>
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByTestId('trigger');
    trigger.focus();
    expect(document.activeElement).toBe(trigger);
    act(() => trigger.click());
    // Drawer mounted; focus is now inside the dialog (close button or
    // body button — both are valid).
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
    // Close via Escape and verify trigger regains focus. Wrap in act()
    // so the state change + effect cleanup flush before the assertion.
    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });
    expect(document.activeElement).toBe(trigger);
  });
});

describe('SideDrawer - close paths', () => {
  it('Escape calls onClose', () => {
    const { onClose } = renderDrawer();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape is suppressed when busy=true', () => {
    const { onClose } = renderDrawer({ busy: true });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('backdrop click closes when backdropCloses is default (true)', () => {
    const { onClose } = renderDrawer();
    const dialog = screen.getByRole('dialog');
    const backdrop = dialog.parentElement as HTMLElement; // outer fixed wrapper
    expect(backdrop).not.toBeNull();
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('backdrop click does NOT close when backdropCloses=false', () => {
    const { onClose } = renderDrawer({ backdropCloses: false });
    const dialog = screen.getByRole('dialog');
    const backdrop = dialog.parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(onClose).not.toHaveBeenCalled();
    // Escape still works in this mode.
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('click inside the panel does NOT call onClose', () => {
    const { onClose } = renderDrawer();
    fireEvent.mouseDown(screen.getByTestId('drawer-body'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('X button click calls onClose', () => {
    const { onClose } = renderDrawer();
    const closeBtn = screen.getByRole('button', { name: 'Close' });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('SideDrawer - body scroll lock', () => {
  it('locks document.body scroll while mounted and restores on unmount', () => {
    document.body.style.overflow = '';
    const { unmount } = render(
      <SideDrawer open onClose={() => undefined} title="x">
        <div>content</div>
      </SideDrawer>,
    );
    expect(document.body.style.overflow).toBe('hidden');
    unmount();
    expect(document.body.style.overflow).toBe('');
  });
});

describe('SideDrawer - headerActions slot', () => {
  it('renders headerActions before the X close button', () => {
    renderDrawer({
      headerActions: (
        <button type="button" data-testid="action-edit">
          Edit
        </button>
      ),
    });
    const editBtn = screen.getByTestId('action-edit');
    const closeBtn = screen.getByRole('button', { name: 'Close' });
    expect(editBtn).toBeInTheDocument();
    // Edit appears before Close in document order.
    const position = editBtn.compareDocumentPosition(closeBtn);
    // eslint-disable-next-line no-bitwise
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('SideDrawer - nested overlay', () => {
  function Host({ onDrawerClose }: { onDrawerClose: () => void }) {
    const [modal, setModal] = useState(false);
    return (
      <SideDrawer open onClose={onDrawerClose} title="Contract">
        <button type="button" onClick={() => setModal(true)}>
          open-gate
        </button>
        <WideModal open={modal} onClose={() => setModal(false)} title="Gate">
          <button type="button" data-testid="modal-a">
            a
          </button>
          <button type="button" data-testid="modal-b">
            b
          </button>
        </WideModal>
      </SideDrawer>
    );
  }

  it('does not pull Tab out of a modal opened inside the drawer', () => {
    const onDrawerClose = vi.fn();
    render(<Host onDrawerClose={onDrawerClose} />);
    fireEvent.click(screen.getByText('open-gate'));
    const last = screen.getByTestId('modal-b');
    act(() => last.focus());
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    act(() => {
      last.dispatchEvent(ev);
    });
    // The modal trap wraps to its own first control; the drawer must not
    // have moved focus to its own.
    expect(document.activeElement?.closest('[role="dialog"]')?.textContent).toContain('Gate');
  });

  it('Escape closes only the modal, then the drawer once the modal is gone', () => {
    const onDrawerClose = vi.fn();
    render(<Host onDrawerClose={onDrawerClose} />);
    fireEvent.click(screen.getByText('open-gate'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDrawerClose).not.toHaveBeenCalled();
    expect(screen.queryByText('Gate')).toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDrawerClose).toHaveBeenCalledTimes(1);
  });
});
