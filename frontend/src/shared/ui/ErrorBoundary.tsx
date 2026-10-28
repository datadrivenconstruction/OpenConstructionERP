// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React from 'react';
import { AlertTriangle, RotateCcw, Home } from 'lucide-react';
import i18n from '@/app/i18n';
import { logError } from '@/shared/lib/errorLogger';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  /**
   * What this boundary stands in front of, which decides what "try again" can
   * honestly do.
   *
   * `'page'` (the default) wraps a route's content while the sidebar and header
   * stay mounted and usable. The caller keys it by pathname, so the user has a
   * second escape route — navigate somewhere else and the subtree remounts —
   * and clearing the error state is enough for the button.
   *
   * `'app'` wraps the application chrome itself. Nothing outside it survives to
   * navigate with, and no key remounts it, so clearing the state would re-render
   * the same shell against the same cached data and trip again on the spot.
   * There the button reloads the document, which drops the caches that fed the
   * crash and is the only recovery a user can actually reach.
   */
  scope?: 'page' | 'app';
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches React render errors and displays a recovery UI instead of a white screen.
 * Wraps page-level routes so a crash in one page doesn't break the whole app.
 *
 * Mounted twice in AppShell, nested. The inner one is keyed by pathname and
 * covers the page; the outer one is `scope="app"` and covers the chrome, which
 * used to render above every boundary and could therefore take the document
 * blank on its own. React hands a throw to the nearest boundary below, so a
 * page crash never reaches the outer one and the sidebar stays usable.
 *
 * A fallback must not be able to throw. The default one below can't: `i18n.t`
 * returns a string or the key even before init, `state.error` is null-checked,
 * and the rest is inert markup. The `fallback` prop is the caller's risk — a
 * node that throws re-raises to the parent boundary, and past the outermost one
 * that is the blank screen again, so keep custom fallbacks trivial.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack);
    logError(error, 'react_error', {
      componentStack: info.componentStack ?? '',
    });
    // "Failed to fetch dynamically imported module" is the canonical stale-
    // chunk error: the running build replaced chunks with new hashes (a fresh
    // deploy, or active local development with the tab left open) but this
    // browser still holds references to the old hashed URLs. A reload fetches
    // the current index.html with the live chunk graph and the app recovers.
    //
    // The guard is time-based, not count-based, and shares its key with the
    // vite:preloadError handler in main.tsx so the two recovery paths cannot
    // double-reload. A stale chunk that recurs later in the same session (the
    // next deploy, the next local rebuild) gets its own reload; but two chunk
    // crashes inside the window mean the freshly fetched build is genuinely
    // broken, so we stop and let the boundary render the recovery UI rather
    // than loop. A count-based one-shot guard dead-ended the *second* distinct
    // stale chunk of a session, which is exactly the case active development
    // produces.
    const msg = String(error?.message ?? '');
    const isChunkError =
      msg.includes('Failed to fetch dynamically imported module') ||
      msg.includes('Importing a module script failed') ||
      /Loading chunk \d+ failed/i.test(msg);
    if (isChunkError) {
      // Reading sessionStorage is not a safe operation: browsers configured to
      // block site data, and sandboxed frames, throw SecurityError on the
      // property access itself. A throw from componentDidCatch is re-raised to
      // the PARENT boundary, and the outermost boundary has no parent — React
      // unmounts the whole tree and the user gets the blank document this class
      // exists to prevent. So the storage that only tunes the reload heuristic
      // must never be able to take the recovery UI down with it: on failure we
      // skip the auto-reload and render the fallback, which is the safe branch.
      try {
        const KEY = 'oe_chunk_reload_at';
        const last = Number(sessionStorage.getItem(KEY) ?? '0');
        if (Date.now() - last > 10_000) {
          sessionStorage.setItem(KEY, String(Date.now()));
          window.location.reload();
          return;
        }
        // Reloaded moments ago for the same reason → the new build is broken;
        // fall through and render the recovery UI instead of looping.
      } catch {
        // Storage unavailable — fall through to the recovery UI.
      }
    }
  }

  handleReset = () => {
    // At app scope the same render is all there is: clearing the flag would
    // rebuild the chrome from the caches that just crashed it, so the button
    // would blink and change nothing. Reload instead — same promise to the
    // user, kept.
    if (this.props.scope === 'app') {
      window.location.reload();
      return;
    }
    this.setState({ hasError: false, error: null });
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      // At app scope this card IS the document — the chrome that would have
      // supplied a page area is the thing that crashed — so it takes the full
      // viewport. No background class: `body` already paints
      // `--oe-bg-secondary`, and AppLayout deliberately leaves it to do that.
      return (
        <div
          className={`flex ${this.props.scope === 'app' ? 'min-h-screen' : 'min-h-[60vh]'} items-center justify-center p-8`}
          data-testid="error-boundary-fallback"
        >
          <div className="max-w-md text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-semantic-error-bg">
              <AlertTriangle size={28} className="text-semantic-error" />
            </div>
            <h2 className="mb-2 text-xl font-semibold text-content-primary">
              {i18n.t('error.something_wrong')}
            </h2>
            <p className="mb-6 text-sm text-content-secondary">
              {i18n.t('error.unexpected_error')}
            </p>
            {this.state.error && (
              <details className="mb-6 rounded-lg border border-border-light bg-surface-secondary p-3 text-left">
                <summary className="cursor-pointer text-xs font-medium text-content-secondary">
                  {i18n.t('error.details')}
                </summary>
                <pre className="mt-2 overflow-x-auto text-xs text-semantic-error">
                  {this.state.error.message}
                </pre>
              </details>
            )}
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleReset}
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-elevated px-4 py-2 text-sm font-medium text-content-primary transition-colors hover:bg-surface-secondary"
              >
                <RotateCcw size={14} />
                {i18n.t('error.try_again')}
              </button>
              <button
                onClick={this.handleGoHome}
                className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-oe-blue-dark"
              >
                <Home size={14} />
                {i18n.t('error.go_dashboard')}
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
