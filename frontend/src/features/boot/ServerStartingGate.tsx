/**
 * The setup screen shown while the server is still starting.
 *
 * The backend opens its port within seconds and finishes startup behind it; a
 * first run spends minutes on the database and the modules. Until it is done
 * every API call answers 503, so instead of pages that fail one by one this
 * shows which step is running and opens the app by itself when the server is
 * ready. Demo projects and cost data then keep loading in the background,
 * reported by the background services in the top bar.
 *
 * Fails open: when the health probe cannot be reached at all (offline, a proxy
 * that hides it) the app renders as before.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { API_BASE } from '@/shared/lib/api';
import { parseBootBody, useServerBootStore, type BootSnapshot } from '@/stores/useServerBootStore';

/** How often the setup screen asks again. */
export const BOOT_POLL_MS = 2000;
/** How long the first check may hold the app back before it renders anyway. */
export const BOOT_FIRST_CHECK_MS = 1500;

const PHASE_KEYS: Record<string, string> = {
  startup: 'starting',
  OpenConstructionERP: 'starting',
  i18n: 'translations',
  Database: 'database',
  Modules: 'modules',
  Validation: 'validation',
  'Demo data': 'demo_data',
  'Vector DB': 'services',
  Ready: 'finishing',
  Routing: 'finishing',
};

const PHASE_DEFAULTS: Record<string, string> = {
  starting: 'Starting the server',
  translations: 'Loading translations',
  database: 'Preparing the database',
  modules: 'Loading modules',
  validation: 'Registering validation rules',
  demo_data: 'Creating demo accounts and reference data',
  services: 'Preparing background services',
  finishing: 'Finishing',
};

type Probe = { kind: 'ready' } | { kind: 'starting'; boot: BootSnapshot } | { kind: 'unreachable' };

export async function probeServer(signal?: AbortSignal): Promise<Probe> {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: 'no-store', signal });
    if (res.ok) return { kind: 'ready' };
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    const boot = parseBootBody(res.status, body);
    return boot ? { kind: 'starting', boot } : { kind: 'unreachable' };
  } catch {
    return { kind: 'unreachable' };
  }
}

function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

export function ServerStartingScreen({ boot, failed }: { boot: BootSnapshot | null; failed: boolean }) {
  const { t } = useTranslation();
  // The server's elapsed time, carried forward locally so the clock keeps
  // moving while a busy server is slow to answer the next probe.
  const [tick, setTick] = useState(0);
  const base = useRef<{ at: number; elapsed: number }>({ at: Date.now(), elapsed: 0 });
  useEffect(() => {
    base.current = { at: Date.now(), elapsed: boot?.elapsed_seconds ?? 0 };
  }, [boot]);
  useEffect(() => {
    if (failed) return undefined;
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [failed]);
  void tick;
  const elapsed = base.current.elapsed + (Date.now() - base.current.at) / 1000;

  const phaseKey = boot ? PHASE_KEYS[boot.phase] ?? 'starting' : 'starting';
  const phaseLabel = t(`boot.phase.${phaseKey}`, { defaultValue: PHASE_DEFAULTS[phaseKey] ?? phaseKey });
  const steps = boot?.steps ?? 0;
  const step = boot?.step ?? 0;
  const pct = steps > 0 && step > 0 ? Math.min(100, Math.round(((step - 1) / steps) * 100)) : 0;

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary px-4" data-testid="server-starting-screen">
      <div
        role="status"
        aria-live="polite"
        className="w-full max-w-md rounded-2xl border border-border-light bg-surface-primary p-6 shadow-sm"
      >
        {failed ? (
          <>
            <div className="mb-3 flex items-center gap-2 text-semantic-error">
              <AlertTriangle size={18} aria-hidden />
              <h1 className="text-base font-semibold">
                {t('boot.failed_title', { defaultValue: 'The server could not start' })}
              </h1>
            </div>
            <p className="text-sm text-content-secondary">
              {t('boot.failed_body', {
                defaultValue:
                  'Startup stopped with an error. The server log names the cause; start the application again once it is fixed.',
              })}
            </p>
          </>
        ) : (
          <>
            <div className="mb-3 flex items-center gap-2">
              <Loader2 size={18} className="animate-spin text-oe-blue" aria-hidden />
              <h1 className="text-base font-semibold text-content-primary">
                {t('boot.starting_title', { defaultValue: 'Setting up OpenConstructionERP' })}
              </h1>
            </div>
            <p className="mb-4 text-sm text-content-secondary">
              {t('boot.starting_body', {
                defaultValue:
                  'The first start prepares the database and loads the modules, which can take a few minutes. This page opens by itself when the server is ready; demo projects and cost data keep loading in the background after that.',
              })}
            </p>
            <div className="mb-1 flex items-center justify-between text-xs text-content-secondary">
              <span data-testid="server-starting-phase">{phaseLabel}</span>
              <span>{formatElapsed(elapsed)}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div className="h-full rounded-full bg-oe-blue transition-all" style={{ width: `${pct}%` }} />
            </div>
            {steps > 0 && step > 0 && (
              <p className="mt-2 text-xs text-content-tertiary">
                {t('boot.step_of', { defaultValue: 'Step {{step}} of {{steps}}', step, steps })}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function ServerStartingGate({ children }: { children: ReactNode }) {
  const phase = useServerBootStore((s) => s.phase);
  const boot = useServerBootStore((s) => s.boot);
  const queryClient = useQueryClient();
  const wasBlocked = useRef(false);

  useEffect(() => {
    if (phase === 'ready' || phase === 'failed') return undefined;
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();
    const { report, setReady } = useServerBootStore.getState();

    // Never hold a working app back for long: if the first answer is slow,
    // render, and let a later "starting" answer bring the screen back.
    const fallback =
      phase === 'checking'
        ? window.setTimeout(() => {
            if (!cancelled && useServerBootStore.getState().phase === 'checking') setReady();
          }, BOOT_FIRST_CHECK_MS)
        : undefined;

    const poll = async () => {
      const probe = await probeServer(controller.signal);
      if (cancelled) return;
      if (probe.kind === 'starting') {
        report(probe.boot);
        if (probe.boot.status === 'starting') timer = window.setTimeout(poll, BOOT_POLL_MS);
        return;
      }
      if (probe.kind === 'ready' || useServerBootStore.getState().phase === 'checking') {
        setReady();
        return;
      }
      // Unreachable while the screen is up: the server is busy or restarting.
      timer = window.setTimeout(poll, BOOT_POLL_MS);
    };
    // Entering "starting" means an answer just arrived: ask again after a pause.
    if (phase === 'checking') void poll();
    else timer = window.setTimeout(poll, BOOT_POLL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
      if (fallback !== undefined) window.clearTimeout(fallback);
    };
  }, [phase]);

  useEffect(() => {
    if (phase === 'starting' || phase === 'failed') wasBlocked.current = true;
    if (phase === 'ready' && wasBlocked.current) {
      wasBlocked.current = false;
      // Anything asked while the API was closed got a 503: ask again.
      void queryClient.invalidateQueries();
    }
  }, [phase, queryClient]);

  if (phase === 'checking') return null;
  if (phase === 'starting' || phase === 'failed') return <ServerStartingScreen boot={boot} failed={phase === 'failed'} />;
  return <>{children}</>;
}
