// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Background services panel: a right-hand drawer that lists every long-running
 * service the platform keeps loaded, grouped by kind, with what it is for,
 * which modules use it, what it costs in memory and how it is doing. An
 * administrator turns each one on, off or restarts it without restarting the
 * platform; everyone else sees the same view read-only.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import clsx from 'clsx';
import {
  Brain,
  CalendarClock,
  Check,
  ChevronDown,
  Copy,
  Feather,
  Flame,
  Lock,
  Wrench,
  Loader2,
  RefreshCw,
  RotateCw,
  Search,
  Sparkles,
  X,
  type LucideIcon,
} from 'lucide-react';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  CATEGORY_ORDER,
  isControllable,
  isLoading,
  isOn,
  ramOf,
  useMinimalPreset,
  useProcessAction,
  useProcesses,
  type ProcessAction,
  type ProcessCategory,
  type ProcessInfo,
  type ProcessStatus,
} from './api';
import { formatMb, moduleLink, processName, processOffImpact, processPurpose, useIsProcessAdmin } from './labels';
import { useProcessesUi } from './useProcessesUi';

/** The memory floor the core is sized for (docs/INSTALL_LINUX.md): the bar reads against it. */
const SERVER_BUDGET_MB = 3072;

const CATEGORY_ICON: Record<ProcessCategory, LucideIcon> = {
  ai_model: Brain,
  vector_index: Search,
  scheduler: CalendarClock,
  cache_warmup: Flame,
  sync: RefreshCw,
  maintenance: Wrench,
};

const STATUS_STYLE: Record<ProcessStatus, string> = {
  running: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300',
  disabled: 'bg-slate-500/10 text-content-secondary ring-slate-500/25',
  idle: 'bg-sky-500/10 text-sky-700 ring-sky-500/30 dark:text-sky-300',
  starting: 'bg-amber-500/10 text-amber-700 ring-amber-500/30 dark:text-amber-300',
  stopping: 'bg-amber-500/10 text-amber-700 ring-amber-500/30 dark:text-amber-300',
  degraded: 'bg-amber-500/10 text-amber-700 ring-amber-500/30 dark:text-amber-300',
  error: 'bg-rose-500/10 text-rose-700 ring-rose-500/30 dark:text-rose-300',
};

export function statusLabel(t: TFunction, s: ProcessStatus): string {
  switch (s) {
    case 'running':
      return t('processes.status.running', { defaultValue: 'Running' });
    case 'disabled':
      return t('processes.status.disabled', { defaultValue: 'Off' });
    case 'idle':
      return t('processes.status.idle', { defaultValue: 'Ready, loads when needed' });
    case 'starting':
      return t('processes.status.starting', { defaultValue: 'Starting' });
    case 'stopping':
      return t('processes.status.stopping', { defaultValue: 'Stopping' });
    case 'degraded':
      return t('processes.status.degraded', { defaultValue: 'Needs attention' });
    case 'error':
      return t('processes.status.error', { defaultValue: 'Error' });
  }
}

function categoryLabel(t: TFunction, c: ProcessCategory): string {
  switch (c) {
    case 'ai_model':
      return t('processes.category.ai_model', { defaultValue: 'AI models' });
    case 'vector_index':
      return t('processes.category.vector_index', { defaultValue: 'Search indexes' });
    case 'scheduler':
      return t('processes.category.scheduler', { defaultValue: 'Schedulers' });
    case 'cache_warmup':
      return t('processes.category.cache_warmup', { defaultValue: 'Warm-up' });
    case 'sync':
      return t('processes.category.sync', { defaultValue: 'Messaging and jobs' });
    case 'maintenance':
      return t('processes.category.maintenance', { defaultValue: 'Housekeeping' });
  }
}

export function StatusPill({ status, queued = false }: { status: ProcessStatus; queued?: boolean }) {
  const { t } = useTranslation();
  const busy = queued || status === 'starting' || status === 'stopping';
  return (
    <span
      data-testid="process-status"
      data-status={queued ? 'queued' : status}
      className={clsx(
        'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset',
        queued ? STATUS_STYLE.starting : STATUS_STYLE[status],
      )}
    >
      {busy && <Loader2 size={10} className="animate-spin" aria-hidden />}
      {queued ? t('processes.status.queued', { defaultValue: 'Waiting to load' }) : statusLabel(t, status)}
    </span>
  );
}

function Toggle({
  on,
  disabled,
  label,
  onChange,
}: {
  on: boolean;
  disabled: boolean;
  label: string;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      data-testid="process-toggle"
      className={clsx(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50',
        on ? 'bg-oe-blue' : 'bg-slate-300 dark:bg-slate-600',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span
        aria-hidden
        className={clsx(
          'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
          on ? 'translate-x-[18px] rtl:-translate-x-[18px]' : 'translate-x-0.5 rtl:-translate-x-0.5',
        )}
      />
    </button>
  );
}

function RamBar({ mb, max }: { mb: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.max(3, (mb / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary" aria-hidden>
      <div className="h-full rounded-full bg-oe-blue/70" style={{ width: `${pct}%` }} />
    </div>
  );
}

function ProcessRow({
  p,
  maxRam,
  isAdmin,
  expanded,
  onToggleExpand,
  onAction,
  pending,
}: {
  p: ProcessInfo;
  maxRam: number;
  isAdmin: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onAction: (action: ProcessAction) => void;
  pending: boolean;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const Icon = CATEGORY_ICON[p.category] ?? Sparkles;
  const name = processName(t, p);
  const purpose = processPurpose(t, p);
  const offImpact = processOffImpact(t, p);
  const detailsId = `process-details-${p.id}`;
  const busy = pending || isLoading(p) || p.status === 'stopping';
  const controllable = isControllable(p);
  const canRestart =
    controllable && p.enabled && (p.status === 'running' || p.status === 'error' || p.status === 'degraded');
  const mb = ramOf(p);

  const copyError = async () => {
    if (!p.last_error) return;
    try {
      await navigator.clipboard.writeText(p.last_error.message);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked - the text stays selectable */
    }
  };

  return (
    <li
      data-testid={`process-row-${p.id}`}
      data-process-id={p.id}
      className="rounded-xl border border-border-light bg-surface-elevated p-3"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue dark:text-sky-300">
          <Icon size={16} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h4 className="min-w-0 break-words text-sm font-semibold text-content-primary">{name}</h4>
            <StatusPill status={p.status} queued={p.queued === true && p.status === 'idle'} />
            {(p.required || !p.stoppable) && (
              <span className="text-2xs font-medium text-content-tertiary">
                {t('processes.required', { defaultValue: 'Always on' })}
              </span>
            )}
            {p.env_locked && !p.required && (
              <span
                className="inline-flex items-center gap-1 text-2xs font-medium text-content-tertiary"
                title={t('processes.env_locked_hint', {
                  defaultValue: 'The server configuration decides this one, so the switch is locked.',
                })}
              >
                <Lock size={10} aria-hidden />
                {t('processes.env_locked', { defaultValue: 'Set by server config' })}
              </span>
            )}
          </div>
          {purpose && <p className="mt-0.5 text-xs text-content-secondary">{purpose}</p>}
          {p.modules.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              <span className="text-2xs text-content-tertiary">
                {t('processes.used_by', { defaultValue: 'Used by' })}
              </span>
              {p.modules.map((m) => {
                const link = moduleLink(t, m);
                const cls =
                  'inline-flex max-w-full items-center truncate rounded-md bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary';
                return link.to ? (
                  <Link key={m} to={link.to} className={clsx(cls, 'hover:bg-oe-blue/10 hover:text-oe-blue')}>
                    {link.label}
                  </Link>
                ) : (
                  <span key={m} className={cls}>
                    {link.label}
                  </span>
                );
              })}
            </div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1">
              <RamBar mb={mb} max={maxRam} />
            </div>
            <span className="shrink-0 text-2xs tabular-nums text-content-tertiary">
              {p.ram_mb_actual == null
                ? t('processes.ram_estimate', { defaultValue: '~{{value}}', value: formatMb(t, mb) })
                : formatMb(t, mb)}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Toggle
            on={p.enabled}
            disabled={!isAdmin || !controllable || busy}
            label={
              p.enabled
                ? t('processes.turn_off', { defaultValue: 'Turn off {{name}}', name })
                : t('processes.turn_on', { defaultValue: 'Turn on {{name}}', name })
            }
            onChange={(next) => onAction(next ? 'enable' : 'disable')}
          />
          <div className="flex items-center gap-1">
            {isAdmin && canRestart && (
              <button
                type="button"
                onClick={() => onAction('restart')}
                disabled={busy}
                data-testid="process-restart"
                aria-label={t('processes.restart', { defaultValue: 'Restart {{name}}', name })}
                title={t('processes.restart', { defaultValue: 'Restart {{name}}', name })}
                className="flex h-7 w-7 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
              >
                <RotateCw size={14} aria-hidden />
              </button>
            )}
            <button
              type="button"
              onClick={onToggleExpand}
              aria-expanded={expanded}
              aria-controls={detailsId}
              data-testid="process-expand"
              aria-label={t('processes.details', { defaultValue: 'Details' })}
              title={t('processes.details', { defaultValue: 'Details' })}
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary"
            >
              <ChevronDown size={14} className={clsx('transition-transform', expanded && 'rotate-180')} aria-hidden />
            </button>
          </div>
        </div>
      </div>

      {expanded && (
        <div id={detailsId} className="mt-3 space-y-3 border-t border-border-light pt-3 text-xs">
          {offImpact && (
            <div>
              <div className="font-semibold text-content-primary">
                {t('processes.if_off', { defaultValue: 'If you turn this off' })}
              </div>
              <p className="mt-0.5 text-content-secondary">{offImpact}</p>
            </div>
          )}
          {p.restart_count > 0 && (
            <p className="text-content-tertiary">
              {t('processes.restarts', {
                defaultValue: 'Restarted automatically {{count}} times since the server started.',
                count: p.restart_count,
              })}
            </p>
          )}
          {p.last_error && (
            <div role="alert" className="rounded-lg bg-rose-500/10 p-2 text-rose-800 dark:text-rose-200">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{t('processes.last_error', { defaultValue: 'Last error' })}</span>
                <button
                  type="button"
                  onClick={copyError}
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-rose-500/10"
                >
                  {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
                  {copied
                    ? t('processes.copied', { defaultValue: 'Copied' })
                    : t('processes.copy', { defaultValue: 'Copy' })}
                </button>
              </div>
              <p className="mt-1 break-words font-mono">{p.last_error.message}</p>
            </div>
          )}
          <div>
            <div className="font-semibold text-content-primary">
              {t('processes.recent_log', { defaultValue: 'Recent activity' })}
            </div>
            {p.log_tail.length > 0 ? (
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-secondary p-2 font-mono text-2xs text-content-secondary">
                {p.log_tail.slice(-10).join('\n')}
              </pre>
            ) : (
              <p className="mt-0.5 text-content-tertiary">
                {t('processes.no_log', { defaultValue: 'Nothing logged yet.' })}
              </p>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export function ProcessesPanel() {
  const { t } = useTranslation();
  const open = useProcessesUi((s) => s.panelOpen);
  const focusId = useProcessesUi((s) => s.focusId);
  const close = useProcessesUi((s) => s.closePanel);
  const openWizard = useProcessesUi((s) => s.openWizard);
  const isAdmin = useIsProcessAdmin();
  const { data, isLoading, isError, error, refetch } = useProcesses(open);
  const action = useProcessAction();
  const minimal = useMinimalPreset();
  const addToast = useToastStore((s) => s.addToast);
  const panelRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useFocusTrap(panelRef, open);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  // Opened from a module banner: unfold that row and bring it into view.
  useEffect(() => {
    if (!open || !focusId || !data) return;
    setExpanded((s) => new Set(s).add(focusId));
    const el = panelRef.current?.querySelector(`[data-process-id="${CSS.escape(focusId)}"]`);
    el?.scrollIntoView?.({ block: 'center' });
  }, [open, focusId, data]);

  const processes = data?.processes ?? [];
  const groups = useMemo(
    () =>
      CATEGORY_ORDER.map((c) => ({ category: c, items: processes.filter((p) => p.category === c) })).filter(
        (g) => g.items.length > 0,
      ),
    [processes],
  );
  const maxRam = Math.max(1, ...processes.map(ramOf));
  const running = processes.filter(isOn).length;
  const usedMb = data?.total_ram_mb_estimate ?? 0;
  const rssMb = data?.process_rss_mb ?? null;
  const budgetPct = Math.min(100, (usedMb / SERVER_BUDGET_MB) * 100);

  if (!open) return null;

  const run = (p: ProcessInfo, a: ProcessAction) =>
    action.mutate(
      { id: p.id, action: a },
      {
        onError: (err) =>
          addToast({
            type: 'error',
            title: t('processes.action_failed', {
              defaultValue: 'Could not change {{name}}',
              name: processName(t, p),
            }),
            message: getErrorMessage(err),
          }),
      },
    );

  const title = t('processes.title', { defaultValue: 'Background services' });

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="processes-panel">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={close} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="processes-panel-title"
        className="relative flex h-full w-full max-w-full flex-col bg-surface-primary shadow-2xl animate-slide-in-right sm:w-[30rem]"
      >
        <header className="flex items-start gap-3 border-b border-border-light px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <h2 id="processes-panel-title" className="text-base font-semibold text-content-primary">
              {title}
            </h2>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('processes.subtitle', {
                defaultValue:
                  'Things the platform keeps running for you. Turn off what you do not use to free memory.',
              })}
            </p>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary"
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-content-secondary">
              <Loader2 size={14} className="animate-spin" aria-hidden />
              {t('processes.loading', { defaultValue: 'Checking services...' })}
            </div>
          )}

          {isError && !data && (
            <div role="alert" className="rounded-xl bg-rose-500/10 p-3 text-sm text-rose-800 dark:text-rose-200">
              <p>{t('processes.load_failed', { defaultValue: 'Could not read the status of the services.' })}</p>
              <p className="mt-1 text-xs opacity-80">{getErrorMessage(error)}</p>
              <button type="button" onClick={() => refetch()} className="mt-2 text-xs font-semibold underline">
                {t('common.retry', { defaultValue: 'Retry' })}
              </button>
            </div>
          )}

          {data && (
            <>
              <section
                aria-label={t('processes.summary_label', { defaultValue: 'Summary' })}
                className="rounded-xl border border-border-light bg-surface-elevated p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className="text-sm font-semibold text-content-primary" data-testid="processes-summary">
                    {t('processes.summary', {
                      defaultValue: '{{running}} of {{total}} on',
                      running,
                      total: processes.length,
                    })}
                  </span>
                  <span className="text-xs tabular-nums text-content-secondary">
                    {t('processes.memory_used', {
                      defaultValue: 'about {{used}} of memory',
                      used: formatMb(t, usedMb),
                    })}
                  </span>
                </div>
                {rssMb != null && (
                  <p className="mt-1 text-2xs text-content-tertiary">
                    {t('processes.rss', {
                      defaultValue: 'The whole server uses {{value}} right now. Memory may take a while to come back after you turn something off.',
                      value: formatMb(t, rssMb),
                    })}
                  </p>
                )}
                <div
                  className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-secondary"
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={SERVER_BUDGET_MB}
                  aria-valuenow={Math.round(usedMb)}
                  aria-label={t('processes.memory_meter', {
                    defaultValue: 'Memory used by services out of a {{budget}} server',
                    budget: formatMb(t, SERVER_BUDGET_MB),
                  })}
                >
                  <div
                    className={clsx('h-full rounded-full', budgetPct > 80 ? 'bg-amber-500' : 'bg-emerald-500')}
                    style={{ width: `${budgetPct}%` }}
                  />
                </div>
                {isAdmin ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => minimal.mutate()}
                      disabled={minimal.isPending}
                      data-testid="processes-minimal"
                      title={t('processes.minimal_hint', {
                        defaultValue: 'Keep only what the platform cannot run without',
                      })}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-50"
                    >
                      <Feather size={12} aria-hidden />
                      {t('processes.minimal', { defaultValue: 'Minimal mode' })}
                    </button>
                    <button
                      type="button"
                      onClick={openWizard}
                      data-testid="processes-open-wizard"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-2.5 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90"
                    >
                      <Sparkles size={12} aria-hidden />
                      {t('processes.setup_for_work', { defaultValue: 'Set up for my work' })}
                    </button>
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-content-tertiary" data-testid="processes-readonly">
                    {t('processes.readonly', { defaultValue: 'Only an administrator can change these.' })}
                  </p>
                )}
              </section>

              {groups.length === 0 && (
                <p className="mt-6 text-center text-sm text-content-secondary">
                  {t('processes.empty', { defaultValue: 'No background services are registered.' })}
                </p>
              )}

              {groups.map((g) => (
                <section key={g.category} className="mt-5" aria-labelledby={`processes-cat-${g.category}`}>
                  <h3
                    id={`processes-cat-${g.category}`}
                    className="mb-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary"
                  >
                    {categoryLabel(t, g.category)}
                  </h3>
                  <ul className="space-y-2">
                    {g.items.map((p) => (
                      <ProcessRow
                        key={p.id}
                        p={p}
                        maxRam={maxRam}
                        isAdmin={isAdmin}
                        expanded={expanded.has(p.id)}
                        pending={action.isPending && action.variables?.id === p.id}
                        onToggleExpand={() =>
                          setExpanded((s) => {
                            const n = new Set(s);
                            if (n.has(p.id)) n.delete(p.id);
                            else n.add(p.id);
                            return n;
                          })
                        }
                        onAction={(a) => run(p, a)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
