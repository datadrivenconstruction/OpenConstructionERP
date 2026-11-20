// Design module (ERP side of the design editor link).
import { useEffect, useRef } from 'react';

/**
 * Ask before unsaved edits are lost. The ERP runs on a plain browser router (no data router, so no
 * route blocker): in-app links are caught in the capture phase before the router sees the click,
 * the browser Back button is undone when declined, and closing or reloading uses `beforeunload`.
 */
export function useLeaveGuard(active: boolean, message: string): void {
  const state = useRef({ active, message });
  state.current = { active, message };

  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {
      if (!state.current.active) return;
      e.preventDefault();
      e.returnValue = '';
    };
    const click = (e: MouseEvent) => {
      if (!state.current.active || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
      if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download')) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return; // a new document: beforeunload asks
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (!window.confirm(state.current.message)) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    let undoing = false;
    const pop = () => {
      if (undoing || !state.current.active) return;
      if (!window.confirm(state.current.message)) {
        undoing = true;
        window.history.go(1); // back to the page we left; the guard ignores that popstate
        setTimeout(() => { undoing = false; }, 300);
      }
    };
    window.addEventListener('beforeunload', unload);
    document.addEventListener('click', click, true);
    window.addEventListener('popstate', pop);
    return () => {
      window.removeEventListener('beforeunload', unload);
      document.removeEventListener('click', click, true);
      window.removeEventListener('popstate', pop);
    };
  }, []);
}
