// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * First-run choice of background services. The platform starts minimal; an
 * administrator ticks the parts of the product they will use and sees which
 * services those need and how much memory that adds, then starts them now or
 * later. Shown once on its own (while the server says the choice was never
 * made) and reopenable from the panel at any time.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, Loader2, X } from 'lucide-react';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { compareNames } from '@/shared/lib/collator';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { processesForModules, ramOf, useFirstRun, useProcesses, type ProcessCategory } from './api';

/** Kinds of service that load a model or an index into memory. */
const HEAVY = new Set<ProcessCategory>(['ai_model', 'vector_index']);
import { formatMb, moduleLink, processName, useIsProcessAdmin } from './labels';
import { useProcessesUi } from './useProcessesUi';

export function ProcessesWizard() {
  const { t } = useTranslation();
  const isAdmin = useIsProcessAdmin();
  const wizardOpen = useProcessesUi((s) => s.wizardOpen);
  const closeWizard = useProcessesUi((s) => s.closeWizard);
  const { data } = useProcesses(wizardOpen);
  const firstRun = useFirstRun();
  const addToast = useToastStore((s) => s.addToast);
  const ref = useRef<HTMLDivElement>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  useFocusTrap(ref, wizardOpen);

  const processes = data?.processes ?? [];
  const modules = useMemo(() => {
    const ids = new Set<string>();
    for (const p of processes) if (!p.required && p.stoppable) p.modules.forEach((m) => ids.add(m));
    return [...ids]
      .map((id) => {
        // What this module would add on its own: the AI models and search
        // indexes it pulls in. Light loops are not worth a number.
        const heavyMb = processes
          .filter((p) => p.modules.includes(id) && HEAVY.has(p.category))
          .reduce((sum, p) => sum + ramOf(p), 0);
        return { ...moduleLink(t, id), heavyMb };
      })
      .sort((a, b) => a.heavyMb - b.heavyMb || compareNames(a.label, b.label));
  }, [processes, t]);

  // Seed the ticks once per opening, not on every poll, or a refresh would
  // undo what the user just clicked. First run: light modules on, anything
  // that loads a model or a search index off (the platform starts light).
  // Reopened later: what is on now.
  const seeded = useRef(false);
  useEffect(() => {
    if (!wizardOpen) {
      seeded.current = false;
      return;
    }
    if (seeded.current || !data) return;
    seeded.current = true;
    const on = new Set<string>();
    if (data.first_run_done) {
      for (const p of data.processes) if (p.enabled && !p.required && p.stoppable) p.modules.forEach((m) => on.add(m));
    } else {
      for (const m of modules) if (m.heavyMb === 0) on.add(m.id);
    }
    setPicked(on);
  }, [wizardOpen, data, modules]);
  const needed = processesForModules(processes, [...picked]);
  const totalMb = needed.reduce((s, p) => s + ramOf(p), 0);

  if (!wizardOpen || !isAdmin) return null;

  const finish = (startNow: boolean) =>
    firstRun.mutate(
      { module_ids: startNow ? [...picked] : [], start_now: startNow },
      {
        onSuccess: () => closeWizard(),
        onError: (err) =>
          addToast({
            type: 'error',
            title: t('processes.wizard.failed', { defaultValue: 'Could not start the services' }),
            message: getErrorMessage(err),
          }),
      },
    );

  const toggle = (id: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-0 sm:p-4" data-testid="processes-wizard">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="processes-wizard-title"
        className="relative flex max-h-full w-full flex-col overflow-hidden bg-surface-primary shadow-2xl animate-scale-in sm:max-h-[90vh] sm:max-w-3xl sm:rounded-2xl"
      >
        <header className="flex items-start gap-3 border-b border-border-light px-4 py-4 sm:px-6">
          <div className="min-w-0 flex-1">
            <h2 id="processes-wizard-title" className="text-lg font-semibold text-content-primary">
              {t('processes.wizard.title', { defaultValue: 'What will you use?' })}
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              {t('processes.wizard.intro', {
                defaultValue:
                  'The platform starts light. Pick the parts you work with and we start only the services they need. You can change this any time from Background services in the top bar.',
              })}
            </p>
          </div>
          <button
            type="button"
            onClick={() => finish(false)}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary"
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="grid flex-1 gap-4 overflow-y-auto overflow-x-hidden px-4 py-4 sm:grid-cols-[1fr_16rem] sm:px-6">
          <fieldset>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('processes.wizard.modules', { defaultValue: 'Modules' })}
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {modules.map((m) => {
                const on = picked.has(m.id);
                return (
                  <label
                    key={m.id}
                    data-testid={`wizard-module-${m.id}`}
                    className={clsx(
                      'flex cursor-pointer items-center gap-2 rounded-xl border p-3 text-sm transition-colors',
                      on
                        ? 'border-oe-blue bg-oe-blue/5 text-content-primary'
                        : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(m.id)} />
                    <span
                      aria-hidden
                      className={clsx(
                        'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                        on ? 'border-oe-blue bg-oe-blue text-white' : 'border-border',
                      )}
                    >
                      {on && <Check size={12} />}
                    </span>
                    {m.heavyMb > 0 ? (
                      // Unticked here means "no AI for this module", not "no
                      // module": the label and the hint say which.
                      <span className="min-w-0 flex-1">
                        <span className="block break-words">
                          {t('processes.wizard.heavy_label', { defaultValue: 'AI for {{module}}', module: m.label })}
                        </span>
                        <span className="block text-2xs text-content-tertiary">
                          {m.id === 'search'
                            ? t('processes.wizard.heavy_hint_search', {
                                defaultValue: 'Keyword search works without it.',
                              })
                            : t('processes.wizard.heavy_hint', {
                                defaultValue: '{{module}} works without it.',
                                module: m.label,
                              })}
                        </span>
                      </span>
                    ) : (
                      <span className="min-w-0 flex-1 break-words">{m.label}</span>
                    )}
                    {m.heavyMb > 0 && (
                      <span className="shrink-0 text-xs tabular-nums text-content-tertiary">
                        {t('processes.wizard.adds', { defaultValue: '+{{value}}', value: formatMb(t, m.heavyMb) })}
                      </span>
                    )}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <aside className="rounded-xl bg-surface-secondary p-3" aria-live="polite">
            <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('processes.wizard.will_start', { defaultValue: 'Will start' })}
            </div>
            {needed.length === 0 ? (
              <p className="mt-2 text-sm text-content-secondary">
                {t('processes.wizard.nothing', { defaultValue: 'Nothing extra. The platform stays minimal.' })}
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5 text-sm">
                {needed.map((p) => (
                  <li key={p.id} className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 break-words text-content-primary">{processName(t, p)}</span>
                    <span className="shrink-0 text-xs tabular-nums text-content-tertiary">
                      {formatMb(t, ramOf(p))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div
              className="mt-3 border-t border-border-light pt-2 text-sm font-semibold text-content-primary"
              data-testid="wizard-total"
            >
              {t('processes.wizard.total', { defaultValue: 'Memory: ~{{value}}', value: formatMb(t, totalMb) })}
            </div>
          </aside>
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border-light px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => finish(false)}
            disabled={firstRun.isPending}
            data-testid="wizard-later"
            className="rounded-lg px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
          >
            {t('processes.wizard.later', { defaultValue: 'Later' })}
          </button>
          <button
            type="button"
            onClick={() => finish(true)}
            disabled={firstRun.isPending}
            data-testid="wizard-start"
            className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-sm font-semibold text-white hover:bg-oe-blue/90 disabled:opacity-60"
          >
            {firstRun.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />}
            {t('processes.wizard.start', { defaultValue: 'Start now' })}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
