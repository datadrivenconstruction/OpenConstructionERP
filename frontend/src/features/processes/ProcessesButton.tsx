// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Header entry to the Background services panel: a chip icon, a dot for the
 * overall health and the number of services running. Shown at every width,
 * because it is the way back to a feature that stopped working.
 */

import { useTranslation } from 'react-i18next';
import { Suspense, lazy, useEffect, useRef } from 'react';
import { Cpu, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { isLoading, isOn, isUnsupported, overallHealth, useProcesses } from './api';
import { processName, useIsProcessAdmin } from './labels';
import { useProcessesUi } from './useProcessesUi';

const DOT: Record<string, string> = {
  ok: 'bg-emerald-500',
  busy: 'bg-amber-500',
  error: 'bg-rose-500',
  idle: 'bg-slate-400',
};

// The panel and the wizard are code nobody needs on the first screen: they load
// when opened, so signing in never waits on them.
const ProcessesPanel = lazy(() => import('./ProcessesPanel').then((m) => ({ default: m.ProcessesPanel })));
const ProcessesWizard = lazy(() => import('./ProcessesWizard').then((m) => ({ default: m.ProcessesWizard })));

export function ProcessesButton() {
  const { t } = useTranslation();
  const panelOpen = useProcessesUi((s) => s.panelOpen);
  const wizardOpen = useProcessesUi((s) => s.wizardOpen);
  const openPanel = useProcessesUi((s) => s.openPanel);
  const openWizard = useProcessesUi((s) => s.openWizard);
  const isAdmin = useIsProcessAdmin();
  const { data, isError, error } = useProcesses(panelOpen);
  const offered = useRef(false);

  // Offer the first-run choice once per session while the server has none on record.
  useEffect(() => {
    if (offered.current || !isAdmin || !data || data.first_run_done) return;
    offered.current = true;
    openWizard();
  }, [isAdmin, data, openWizard]);

  const processes = data?.processes ?? [];
  const running = processes.filter(isOn).length;
  const errors = processes.filter((p) => p.status === 'error').length;
  const loading = processes.filter(isLoading);
  const health = isError ? 'error' : overallHealth(processes);

  const title = t('processes.title', { defaultValue: 'Background services' });
  const summary = isError
    ? t('processes.header_unreachable', { defaultValue: 'Background services: status unavailable' })
    : loading.length > 0
      ? t('processes.header_summary_loading', {
          defaultValue: 'Background services: preparing {{names}}',
          names: loading.map((p) => processName(t, p)).join(', '),
        })
      : errors > 0
      ? t('processes.header_summary_errors', {
          defaultValue: 'Background services: {{running}} on, {{errors}} with errors',
          running,
          errors,
        })
      : t('processes.header_summary', { defaultValue: 'Background services: {{running}} on', running });

  if (isUnsupported(error)) return null;

  return (
    <>
    <button
      type="button"
      onClick={() => openPanel()}
      aria-label={summary}
      aria-haspopup="dialog"
      aria-expanded={panelOpen}
      title={loading.length > 0 ? summary : title}
      data-testid="header-processes"
      data-health={health}
      className={clsx(
        'relative flex h-8 shrink-0 items-center gap-1 rounded-lg px-1.5',
        'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
        'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
      )}
    >
      {loading.length > 0 ? (
        <Loader2 size={16} strokeWidth={1.9} className="animate-spin" aria-hidden />
      ) : (
        <Cpu size={16} strokeWidth={1.9} aria-hidden />
      )}
      {data && (
        <span className="min-w-[1ch] text-xs font-semibold tabular-nums" aria-hidden>
          {running}
        </span>
      )}
      <span
        aria-hidden
        className={clsx('absolute right-0.5 top-0.5 h-2 w-2 rounded-full ring-2 ring-surface-primary', DOT[health])}
      />
    </button>
    {(panelOpen || wizardOpen) && (
      <Suspense fallback={null}>
        {panelOpen && <ProcessesPanel />}
        {wizardOpen && <ProcessesWizard />}
      </Suspense>
    )}
    </>
  );
}
