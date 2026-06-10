import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  MinusCircle,
  ChevronDown,
  ChevronUp,
  X,
} from 'lucide-react';
import {
  useBackgroundInstallStore,
  type BgInstallStepStatus,
} from '@/stores/useBackgroundInstallStore';

/**
 * Small, non-blocking floating card that reports the progress of a ready-made
 * pack install that is still provisioning in the BACKGROUND after the user has
 * already entered the app.
 *
 * The onboarding "Ready-made Pack" step applies the language and a minimal
 * workspace fast and routes the user straight to the dashboard. Cost databases,
 * modules and sample projects keep loading on their own; this banner is how the
 * user sees that progress without a full-screen spinner. It is mounted once at
 * the app root (next to the toast container) so it survives navigation, driven
 * entirely by ``useBackgroundInstallStore``.
 *
 * It sits bottom-right so it never collides with the sticky header or the
 * offline banner, is collapsible, and auto-clears a few seconds after a clean
 * finish. A finish with errors stays until the user dismisses it.
 */
export function BackgroundInstallBanner() {
  const { t } = useTranslation();
  const install = useBackgroundInstallStore((s) => s.install);
  const dismiss = useBackgroundInstallStore((s) => s.dismiss);
  const [collapsed, setCollapsed] = useState(false);

  // Auto-clear a clean finish after a short grace window so the banner does not
  // linger forever. A finish with errors is kept until the user dismisses it so
  // the failure stays visible.
  useEffect(() => {
    if (install?.done && !install.hadError) {
      const handle = window.setTimeout(() => dismiss(), 6000);
      return () => window.clearTimeout(handle);
    }
    return undefined;
  }, [install?.done, install?.hadError, dismiss]);

  if (!install) return null;

  const total = install.steps.length;
  const finished = install.steps.filter(
    (s) => s.status === 'ok' || s.status === 'skipped' || s.status === 'error',
  ).length;
  const pct = total > 0 ? Math.round((finished / total) * 100) : 0;
  const runningStep = install.steps.find((s) => s.status === 'running');

  const headline = install.done
    ? install.hadError
      ? t('onboarding.bg_install_done_issues', {
          defaultValue: '{{country}} workspace ready, with some items skipped',
          country: install.country,
        })
      : t('onboarding.bg_install_done', {
          defaultValue: '{{country}} workspace is ready',
          country: install.country,
        })
    : t('onboarding.bg_install_running', {
        defaultValue: 'Setting up {{country}} in the background',
        country: install.country,
      });

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-[9998] w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-border-light/70 bg-surface-elevated/95 shadow-xl shadow-black/10 backdrop-blur-md dark:border-white/10"
    >
      {/* Header row: status icon, headline, percent, collapse + dismiss. */}
      <div className="flex items-center gap-2.5 px-4 pt-3.5 pb-2">
        {install.done ? (
          install.hadError ? (
            <MinusCircle size={18} className="shrink-0 text-semantic-warning" aria-hidden />
          ) : (
            <CheckCircle2 size={18} className="shrink-0 text-semantic-success" aria-hidden />
          )
        ) : (
          <Loader2 size={18} className="shrink-0 animate-spin text-oe-blue" aria-hidden />
        )}
        <p className="flex-1 truncate text-sm font-semibold text-content-primary">{headline}</p>
        <span className="shrink-0 text-xs font-semibold tabular-nums text-content-tertiary">
          {pct}%
        </span>
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={
            collapsed
              ? t('onboarding.bg_install_expand', { defaultValue: 'Show details' })
              : t('onboarding.bg_install_collapse', { defaultValue: 'Hide details' })
          }
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
        >
          {collapsed ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
        {install.done && (
          <button
            type="button"
            onClick={dismiss}
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Determinate progress bar. */}
      <div className="px-4">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
          <div
            className={
              'h-full rounded-full transition-all duration-500 ease-out ' +
              (install.hadError && install.done ? 'bg-semantic-warning' : 'bg-oe-blue')
            }
            style={{ width: `${pct}%` }}
          />
        </div>
        {!install.done && runningStep && (
          <p className="mt-1.5 truncate text-xs text-content-secondary">{runningStep.label}</p>
        )}
      </div>

      {/* Per-step checklist (collapsible). Items reveal their final status as
          each step completes. */}
      {!collapsed && (
        <ul className="space-y-1.5 px-4 pb-3.5 pt-2.5">
          {install.steps.map((s) => (
            <li key={s.step} className="flex items-center gap-2.5 text-xs">
              <BgStepGlyph status={s.status} />
              <span
                className={
                  'flex-1 truncate ' +
                  (s.status === 'error'
                    ? 'text-semantic-error'
                    : s.status === 'ok'
                      ? 'text-content-primary'
                      : 'text-content-secondary')
                }
              >
                {s.label}
              </span>
              {s.detail && (
                <span className="shrink-0 text-2xs text-content-quaternary">{s.detail}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BgStepGlyph({ status }: { status: BgInstallStepStatus }) {
  if (status === 'running') {
    return <Loader2 size={14} className="shrink-0 animate-spin text-oe-blue" aria-hidden />;
  }
  if (status === 'ok') {
    return <CheckCircle2 size={14} className="shrink-0 text-semantic-success" aria-hidden />;
  }
  if (status === 'skipped') {
    return <MinusCircle size={14} className="shrink-0 text-content-quaternary" aria-hidden />;
  }
  if (status === 'error') {
    return <XCircle size={14} className="shrink-0 text-semantic-error" aria-hidden />;
  }
  return (
    <span
      className="h-2.5 w-2.5 shrink-0 rounded-full bg-border-light dark:bg-white/15"
      aria-hidden
    />
  );
}
