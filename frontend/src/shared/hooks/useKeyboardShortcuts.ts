import { useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/** How long (ms) to wait for the second key in a two-key sequence. */
const SEQUENCE_TIMEOUT = 500;

/** Tags where we should never intercept keyboard input. */
const INTERACTIVE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

/** Check whether the active element is an interactive form control. */
function isTyping(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  if (INTERACTIVE_TAGS.has(el.tagName)) return true;
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

export interface UseKeyboardShortcutsOptions {
  onOpenSearch: () => void;
  onToggleShortcutsDialog: () => void;
}

/**
 * Registers global keyboard shortcuts for fast navigation and actions.
 *
 * Single-key shortcuts:
 *   /   - Open search
 *   ?   - Toggle shortcuts help dialog
 *   Esc - Close dialog / cancel
 *
 * Two-key sequences (press first key, then second within 500 ms):
 *   g d - Dashboard
 *   g p - Projects
 *   g b - Bill of Quantities
 *   g c - Cost Database
 *   g a - Assemblies
 *   g v - Validation
 *   g s - 4D Schedule
 *   g f - Finance
 *   g 5 - 5D Cost Model
 *   g r - Reports
 *   g t - Tendering
 *   n p - New Project
 *   n b - New BOQ (via projects page)
 *   n t - New Task
 *
 * Navigation additions:
 *   g m - Meetings
 *   g i - RFI
 *   g o - Contacts
 *
 * Module-local shortcuts (handled per-page, not here):
 *   n   - Open "create new" form on list pages (tasks, meetings, RFI, contacts)
 *   s   - Save / recalculate on BOQ editor
 */
export function useKeyboardShortcuts({
  onOpenSearch,
  onToggleShortcutsDialog,
}: UseKeyboardShortcutsOptions): void {
  const navigate = useNavigate();
  const pendingKeyRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPending = useCallback(() => {
    pendingKeyRef.current = null;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    /** Two-key navigation map: first key -> second key -> path. */
    const sequences: Record<string, Record<string, string>> = {
      g: {
        d: '/',
        p: '/projects',
        b: '/boq',
        c: '/costs',
        a: '/assemblies',
        v: '/validation',
        s: '/schedule',
        f: '/finance',
        '5': '/5d',
        r: '/reports',
        t: '/tendering',
        m: '/meetings',
        i: '/rfi',
        o: '/contacts',
      },
      n: {
        p: '/projects/new',
        b: '/boq',
        t: '/tasks',
      },
    };

    const handler = (e: KeyboardEvent) => {
      // Never intercept when the user is typing in a form field.
      if (isTyping()) {
        clearPending();
        return;
      }

      // Ignore events with modifier keys (Ctrl, Alt, Meta) — those belong to
      // the browser or OS, not our shortcut system.
      if (e.ctrlKey || e.altKey || e.metaKey) return;

      const key = e.key;

      // ── Second key of a pending sequence ──────────────────────────────
      if (pendingKeyRef.current !== null) {
        const firstKey = pendingKeyRef.current;
        clearPending();

        const group = sequences[firstKey];
        const target = group?.[key];
        if (target) {
          e.preventDefault();
          navigate(target);
          return;
        }
        // Fall through — the pending sequence didn't match, so treat this
        // keypress as a potential new first key (handled below).
      }

      // ── Single-key shortcuts ──────────────────────────────────────────
      if (key === '/') {
        e.preventDefault();
        onOpenSearch();
        return;
      }

      if (key === '?') {
        e.preventDefault();
        onToggleShortcutsDialog();
        return;
      }

      // ── Start of a two-key sequence ───────────────────────────────────
      if (key in sequences) {
        e.preventDefault();
        pendingKeyRef.current = key;
        timerRef.current = setTimeout(() => {
          pendingKeyRef.current = null;
          timerRef.current = null;
        }, SEQUENCE_TIMEOUT);
        return;
      }
    };

    document.addEventListener('keydown', handler);
    return () => {
      document.removeEventListener('keydown', handler);
      clearPending();
    };
  }, [navigate, onOpenSearch, onToggleShortcutsDialog, clearPending]);
}
