// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Header entry to the Background services panel: a chip icon, a dot for the
 * overall health and the number of services running. Shown at every width,
 * because it is the way back to a feature that stopped working.
 */

import { useTranslation } from 'react-i18next';
import { Cpu } from 'lucide-react';
import clsx from 'clsx';
import { isOn, isUnsupported, overallHealth, useProcesses } from './api';
import { useProcessesUi } from './useProcessesUi';

const DOT: Record<string, string> = {
  ok: 'bg-emerald-500',
  busy: 'bg-amber-500',
  error: 'bg-rose-500',
  idle: 'bg-slate-400',
};

export function ProcessesButton() {
  const { t } = useTranslation();
  const panelOpen = useProcessesUi((s) => s.panelOpen);
  const openPanel = useProcessesUi((s) => s.openPanel);
  const { data, isError, error } = useProcesses(panelOpen);

  const processes = data?.processes ?? [];
  const running = processes.filter(isOn).length;
  const errors = processes.filter((p) => p.status === 'error').length;
  const health = isError ? 'error' : overallHealth(processes);

  const title = t('processes.title', { defaultValue: 'Background services' });
  const summary = isError
    ? t('processes.header_unreachable', { defaultValue: 'Background services: status unavailable' })
    : errors > 0
      ? t('processes.header_summary_errors', {
          defaultValue: 'Background services: {{running}} on, {{errors}} with errors',
          running,
          errors,
        })
      : t('processes.header_summary', { defaultValue: 'Background services: {{running}} on', running });

  if (isUnsupported(error)) return null;

  return (
    <button
      type="button"
      onClick={() => openPanel()}
      aria-label={summary}
      aria-haspopup="dialog"
      aria-expanded={panelOpen}
      title={title}
      data-testid="header-processes"
      data-health={health}
      className={clsx(
        'relative flex h-8 shrink-0 items-center gap-1 rounded-lg px-1.5',
        'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
        'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
      )}
    >
      <Cpu size={16} strokeWidth={1.9} aria-hidden />
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
  );
}
