// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * PartnerPackApplyDialog - the "activate this pack" preview + live install.
 *
 * The dialog has two phases:
 *
 *   1. Preview  - a dry-run (`GET /v1/partner-pack/apply-preview/{slug}`) of
 *      exactly what the pack changes (currency, default language, validation
 *      standards, which modules switch on or off, the demo project). Disabling
 *      modules is the one destructive effect, so it is gated behind an explicit
 *      opt-in checkbox.
 *
 *   2. Install  - clicking Activate streams the full workspace install
 *      (`POST /v1/partner-pack/full-install-stream`, Server-Sent Events) and
 *      renders a determinate progress bar + a named-step checklist that ticks
 *      over as each step actually runs server-side: apply preset, install
 *      language, load the work catalog (and its bundled resource database),
 *      build the vector index, create the demo project. A pack's work catalog
 *      and resources are installed here, not just its presets - the same
 *      one-click machinery the onboarding "Set up by country" picker uses.
 *
 * Every step is fail-soft; a step that degrades (e.g. no embedding backend) is
 * shown as skipped rather than blocking the activation, and the dialog ends on
 * a success summary with the installed item / resource counts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import i18n, { loadLocaleResource, normalizePackLocale } from '@/app/i18n';
import {
  AlertTriangle,
  Boxes,
  Calculator,
  CheckCircle2,
  Coins,
  Database,
  FolderOpen,
  Globe,
  Languages,
  Loader2,
  MinusCircle,
  Package,
  Power,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { WideModal, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { useApplyPreview } from './partnerPacks';
import {
  fullInstallPackStream,
  type FullInstallStepStatus,
  type StreamInstallEvent,
  type StreamStepDescriptor,
  type StreamStepName,
} from '@/features/onboarding/partnerPacksApi';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { fmtList } from '@/shared/lib/formatters';

interface PartnerPackApplyDialogProps {
  open: boolean;
  onClose: () => void;
  slug: string;
  partnerName: string;
}

/** Lucide icon per install step, matching the onboarding country-pack idiom. */
const STEP_ICONS: Record<StreamStepName, LucideIcon> = {
  apply_pack: Package,
  locale: Languages,
  cost_db: Database,
  resources: Wrench,
  vector_db: Boxes,
  demos: FolderOpen,
};

/** Per-step UI state while/after the streamed install runs. */
type StepUiState = 'pending' | 'running' | FullInstallStepStatus;

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2.5 py-2">
      <span className="mt-0.5 shrink-0 text-content-tertiary">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {label}
        </p>
        <div className="mt-1 text-sm text-content-secondary">{children}</div>
      </div>
    </div>
  );
}

/** Status glyph for one row of the streamed-install checklist. */
function StepGlyph({ state }: { state: StepUiState }) {
  if (state === 'running') {
    return <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" aria-hidden />;
  }
  if (state === 'ok') {
    return <CheckCircle2 size={16} className="text-semantic-success shrink-0" aria-hidden />;
  }
  if (state === 'skipped') {
    return <MinusCircle size={16} className="text-content-quaternary shrink-0" aria-hidden />;
  }
  if (state === 'error') {
    return <XCircle size={16} className="text-semantic-error shrink-0" aria-hidden />;
  }
  return (
    <span
      className="h-2.5 w-2.5 rounded-full bg-border-light dark:bg-white/15 shrink-0"
      aria-hidden
    />
  );
}

/** Human count badge for a step ("12,480 items", "3,200 resources"). */
function asCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function PartnerPackApplyDialog({
  open,
  onClose,
  slug,
  partnerName,
}: PartnerPackApplyDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();

  const { data: preview, isLoading, isError } = useApplyPreview(open ? slug : null);

  const [confirmDisables, setConfirmDisables] = useState(false);
  const [installDemo, setInstallDemo] = useState(true);

  // Install phase state.
  const [installing, setInstalling] = useState(false);
  const [finished, setFinished] = useState<null | { ok: boolean }>(null);
  const [steps, setSteps] = useState<StreamStepDescriptor[]>([]);
  const [stepStates, setStepStates] = useState<Record<string, StepUiState>>({});
  const [stepDetail, setStepDetail] = useState<Record<string, Record<string, unknown>>>({});
  const abortRef = useRef<AbortController | null>(null);

  // Reset everything whenever the dialog (re)opens for a (possibly different) pack.
  useEffect(() => {
    if (open) {
      setConfirmDisables(false);
      setInstallDemo(true);
      setInstalling(false);
      setFinished(null);
      setSteps([]);
      setStepStates({});
      setStepDetail({});
    } else {
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open, slug]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const plan = preview?.plan;
  const willDisable = (plan?.modules_to_disable.length ?? 0) > 0;

  // Determinate progress: completed (non-pending, non-running) steps / total.
  const total = steps.length;
  const completed = useMemo(
    () => steps.filter((s) => ['ok', 'skipped', 'error'].includes(stepStates[s.step] ?? 'pending')).length,
    [steps, stepStates],
  );
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const stepLabel = useCallback(
    (s: StreamStepDescriptor): string => t(s.label_key, { defaultValue: s.label }),
    [t],
  );

  // A short "N items" / "N resources" caption for a finished step, where known.
  const stepCaption = useCallback(
    (step: StreamStepName): string | null => {
      const d = stepDetail[step];
      if (!d) return null;
      if (step === 'cost_db') {
        const items = asCount(d.items);
        return items != null && items > 0
          ? t('modules.pp_caption_items', { defaultValue: '{{count}} items', count: items })
          : null;
      }
      if (step === 'resources') {
        const res = asCount(d.resources);
        return res != null && res > 0
          ? t('modules.pp_caption_resources', { defaultValue: '{{count}} resources', count: res })
          : null;
      }
      if (step === 'vector_db') {
        const vectors = asCount(d.vectors);
        return vectors != null && vectors > 0
          ? t('modules.pp_caption_vectors', { defaultValue: '{{count}} vectors', count: vectors })
          : null;
      }
      if (step === 'demos') {
        const installed = Array.isArray(d.installed) ? d.installed.length : null;
        return installed != null && installed > 0
          ? t('modules.pp_caption_projects', { defaultValue: '{{count}} projects', count: installed })
          : null;
      }
      return null;
    },
    [stepDetail, t],
  );

  // Final summary counts (read off the cost_db / resources steps).
  const summaryItems = asCount(stepDetail.cost_db?.items) ?? 0;
  const summaryResources = asCount(stepDetail.resources?.resources) ?? 0;

  const handleEvent = useCallback((evt: StreamInstallEvent) => {
    if (evt.type === 'start') {
      setSteps(evt.steps);
      const init: Record<string, StepUiState> = {};
      for (const s of evt.steps) init[s.step] = 'pending';
      setStepStates(init);
    } else if (evt.type === 'step_start') {
      setStepStates((prev) => ({ ...prev, [evt.step]: 'running' }));
    } else if (evt.type === 'step_done') {
      setStepStates((prev) => ({ ...prev, [evt.step]: evt.status }));
      setStepDetail((prev) => ({ ...prev, [evt.step]: evt.detail }));
    }
    // ``done`` is handled by the awaiting caller (it carries the overall ok).
  }, []);

  const handleActivate = useCallback(async () => {
    if (installing) return;
    setInstalling(true);
    setFinished(null);
    const controller = new AbortController();
    abortRef.current = controller;

    let ok = false;
    try {
      await fullInstallPackStream(
        slug,
        (evt) => {
          handleEvent(evt);
          if (evt.type === 'done') ok = evt.ok;
        },
        {
          demoCount: installDemo ? 2 : 0,
          confirmDisables,
          signal: controller.signal,
        },
      );
      setFinished({ ok });
      // Refresh the pack queries so the card flips to "Active" + the boot-time
      // co-brand hook re-reads the now-applied pack.
      void qc.invalidateQueries({ queryKey: ['partner-packs'] });
      void qc.invalidateQueries({ queryKey: ['partner-pack-applied'] });
      // The whole prefix, not ['partner-pack', 'current']. React Query matches
      // keys by prefix, so naming 'current' leaves its sibling
      // ['partner-pack', 'installed'] alone, and that sibling is the one the
      // header chip reads. The pack applied and the header went on saying
      // nothing, for as long as the stale entry stayed fresh.
      void qc.invalidateQueries({ queryKey: ['partner-pack'] });
      // Applying a pack enables and disables modules, so the navigation and the
      // dashboard are holding a module list that just changed under them.
      void qc.invalidateQueries({ queryKey: ['modules'] });
      // The backend scopes the project listing to the active pack the instant
      // it is applied, so drop the cached (un-scoped) project list to make the
      // clean single-client view appear immediately (mirrors deactivation).
      void qc.invalidateQueries({ queryKey: ['projects'] });
      if (ok) {
        // Switch the UI language to match the pack's locale immediately.
        // The usePartnerPackLocale hook in AppLayout also does this on
        // data change, but the query refetch is async and the user sees
        // the old language for a beat. Doing it here removes that gap.
        if (plan?.default_locale) {
          const target = normalizePackLocale(plan.default_locale);
          if (target !== 'en' && target !== i18n.language) {
            try {
              window.localStorage.setItem('oce-pack-locale-active', slug);
              window.localStorage.setItem('i18nextLng', target);
            } catch { /* localStorage unavailable */ }
            void loadLocaleResource(target).then(() => i18n.changeLanguage(target));
          }
        }
        addToast({
          type: 'success',
          title: t('modules.pack_applied_title', { defaultValue: 'Pack activated' }),
          message: t('modules.pack_applied_msg', {
            defaultValue: '{{name}} is now the active partner pack.',
            name: partnerName,
          }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('modules.pp_install_partial', {
            defaultValue: 'Some setup steps did not complete',
          }),
          message: t('modules.pp_install_partial_desc', {
            defaultValue: 'Review the checklist. Completed steps are kept.',
          }),
        });
      }
    } catch (err) {
      // Transport failure: mark any still-running step as errored so nothing spins.
      setStepStates((prev) => {
        const next = { ...prev };
        for (const k of Object.keys(next)) {
          if (next[k] === 'running' || next[k] === 'pending') next[k] = 'error';
        }
        return next;
      });
      setFinished({ ok: false });
      if ((err as { name?: string })?.name !== 'AbortError') {
        addToast({
          type: 'error',
          title: t('modules.pack_apply_failed', { defaultValue: 'Could not activate this pack' }),
          message: err instanceof Error ? err.message : undefined,
        });
      }
    } finally {
      setInstalling(false);
      abortRef.current = null;
    }
  }, [installing, slug, installDemo, confirmDisables, handleEvent, qc, addToast, t, partnerName]);

  const showProgress = installing || finished !== null;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="md"
      busy={installing}
      title={t('modules.pack_apply_title', {
        defaultValue: 'Activate {{name}}',
        name: partnerName,
      })}
      subtitle={
        showProgress
          ? t('modules.pp_progress_subtitle', {
              defaultValue: 'Installing the localized workspace for this pack.',
            })
          : t('modules.pack_apply_subtitle', {
              defaultValue: 'Review what this pack changes before you activate it.',
            })
      }
      footer={
        <div className="flex items-center justify-end gap-2">
          {finished ? (
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-oe-blue/90"
            >
              {t('common.done', { defaultValue: 'Done' })}
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                disabled={installing}
                className="rounded-md border border-border bg-surface-primary px-4 py-2 text-sm font-medium text-content-secondary transition hover:bg-surface-secondary disabled:opacity-60"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleActivate}
                disabled={installing || isLoading || isError || showProgress}
                className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {installing ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Power size={15} />
                )}
                {t('modules.pack_activate', { defaultValue: 'Activate pack' })}
              </button>
            </>
          )}
        </div>
      }
    >
      {/* ── Install progress view ──────────────────────────────────────────── */}
      {showProgress ? (
        <div>
          {/* Determinate progress bar. */}
          <div className="mb-1 flex items-center justify-between text-xs font-medium text-content-tertiary">
            <span>
              {finished
                ? finished.ok
                  ? t('modules.pp_done_label', { defaultValue: 'Workspace ready' })
                  : t('modules.pp_partial_label', { defaultValue: 'Finished with warnings' })
                : t('modules.pp_installing_label', { defaultValue: 'Installing…' })}
            </span>
            <span>{pct}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-border-light/80 dark:bg-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-oe-blue via-blue-500 to-purple-500 transition-[width] duration-500 ease-out"
              style={{ width: `${pct}%` }}
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>

          {/* Step checklist. */}
          <ul className="mt-4 space-y-1.5">
            {steps.map((s) => {
              const state = stepStates[s.step] ?? 'pending';
              const Icon = STEP_ICONS[s.step] ?? Package;
              const caption = stepCaption(s.step);
              return (
                <li
                  key={s.step}
                  className="flex items-center gap-3 rounded-lg px-2.5 py-2 transition-colors data-[running=true]:bg-oe-blue-subtle/30"
                  data-running={state === 'running'}
                >
                  <Icon
                    size={16}
                    className={
                      state === 'running'
                        ? 'shrink-0 text-oe-blue'
                        : 'shrink-0 text-content-tertiary'
                    }
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 text-sm text-content-primary">
                    {stepLabel(s)}
                    {caption && (
                      <span className="ms-2 text-xs text-content-tertiary">{caption}</span>
                    )}
                  </span>
                  <StepGlyph state={state} />
                </li>
              );
            })}
          </ul>

          {/* Success / partial summary. */}
          {finished && (
            <div
              className={
                finished.ok
                  ? 'mt-4 flex items-start gap-2 rounded-lg border border-semantic-success/40 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-100'
                  : 'mt-4 flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-amber-50 px-3.5 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-100'
              }
            >
              {finished.ok ? (
                <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              )}
              <span>
                {finished.ok
                  ? t('modules.pp_summary_ok', {
                      defaultValue:
                        'Pack activated. {{items}} catalog items and {{resources}} resources installed.',
                      items: summaryItems.toLocaleString(getNumberLocale()),
                      resources: summaryResources.toLocaleString(getNumberLocale()),
                    })
                  : t('modules.pp_summary_partial', {
                      defaultValue:
                        'Pack activated with some steps skipped. Completed steps are kept; you can re-run activation to retry.',
                    })}
              </span>
            </div>
          )}
        </div>
      ) : (
        <>
          {/* ── Preview view ────────────────────────────────────────────────── */}
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-tertiary">
              <Loader2 size={18} className="animate-spin" />
              {t('modules.pack_preview_loading', {
                defaultValue: 'Checking what will change...',
              })}
            </div>
          )}

          {isError && (
            <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-amber-50 px-3.5 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-100">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              {t('modules.pack_preview_failed', {
                defaultValue:
                  'Could not load the preview for this pack. You can still activate it, but review the pack details first.',
              })}
            </div>
          )}

          {plan && (
            <div className="divide-y divide-border-light">
              <Row
                icon={<Sparkles size={15} />}
                label={t('modules.pack_branding', { defaultValue: 'Branding' })}
              >
                {plan.branding.powered_by}
              </Row>

              <Row
                icon={<Coins size={15} />}
                label={t('modules.pack_currency_locale', {
                  defaultValue: 'Currency & language',
                })}
              >
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  <Badge variant="neutral" size="sm">
                    {plan.default_currency}
                  </Badge>
                  <Badge variant="neutral" size="sm">
                    {plan.default_locale}
                  </Badge>
                  {plan.additional_locales.map((l) => (
                    <Badge key={l} variant="neutral" size="sm">
                      {l}
                    </Badge>
                  ))}
                </span>
              </Row>

              {plan.default_methodology && (
                <Row
                  icon={<Calculator size={15} />}
                  label={t('modules.pack_methodology', {
                    defaultValue: 'Estimating methodology',
                  })}
                >
                  <Badge variant="neutral" size="sm">
                    {plan.default_methodology.replace(/_/g, ' ')}
                  </Badge>
                </Row>
              )}

              {/* Data this activation installs: work catalog + resources. */}
              <Row
                icon={<Database size={15} />}
                label={t('modules.pack_data', { defaultValue: 'Cost data installed' })}
              >
                {plan.cwicr_regions.length > 0 ? (
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    <Badge variant="blue" size="sm">
                      {t('modules.pp_data_catalog', { defaultValue: 'Work catalog' })}
                    </Badge>
                    <Badge variant="blue" size="sm">
                      {t('modules.pp_data_resources', { defaultValue: 'Resource database' })}
                    </Badge>
                    {plan.cwicr_regions.map((r) => (
                      <Badge key={r} variant="neutral" size="sm">
                        {r}
                      </Badge>
                    ))}
                  </span>
                ) : (
                  <span className="text-content-tertiary">
                    {t('modules.pp_data_none', {
                      defaultValue: 'This pack ships presets only (no bundled cost data).',
                    })}
                  </span>
                )}
              </Row>

              {plan.rule_packs_active.length > 0 && (
                <Row
                  icon={<ShieldCheck size={15} />}
                  label={t('modules.pack_standards', {
                    defaultValue: 'Validation standards',
                  })}
                >
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    {plan.rule_packs_active.map((r) => (
                      <Badge key={r} variant="blue" size="sm">
                        {r}
                      </Badge>
                    ))}
                  </span>
                </Row>
              )}

              {plan.modules_to_enable.length > 0 && (
                <Row
                  icon={<Boxes size={15} />}
                  label={t('modules.pack_modules_enable', {
                    defaultValue: 'Modules switched on',
                  })}
                >
                  <span className="text-emerald-600 dark:text-emerald-400">
                    {fmtList(plan.modules_to_enable)}
                  </span>
                </Row>
              )}

              {willDisable && (
                <Row
                  icon={<AlertTriangle size={15} className="text-amber-500" />}
                  label={t('modules.pack_modules_disable', {
                    defaultValue: 'Modules switched off',
                  })}
                >
                  <p className="text-amber-700 dark:text-amber-300">
                    {fmtList(plan.modules_to_disable)}
                  </p>
                  <label className="mt-2 flex cursor-pointer items-start gap-2 rounded-md bg-amber-50 px-2.5 py-2 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-100">
                    <input
                      type="checkbox"
                      checked={confirmDisables}
                      onChange={(e) => setConfirmDisables(e.target.checked)}
                      className="mt-0.5"
                    />
                    <span>
                      {t('modules.pack_confirm_disable', {
                        defaultValue:
                          'Yes, hide these modules from the menu. Leave unchecked to keep them on.',
                      })}
                    </span>
                  </label>
                </Row>
              )}

              {plan.demo_project && (
                <Row
                  icon={<Globe size={15} />}
                  label={t('modules.pack_demo', { defaultValue: 'Demo project' })}
                >
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={installDemo}
                      onChange={(e) => setInstallDemo(e.target.checked)}
                    />
                    <span>
                      {t('modules.pack_demo_install', {
                        defaultValue: 'Install the sample project "{{name}}"',
                        name: plan.demo_project.name ?? plan.demo_project.demo_id,
                      })}
                    </span>
                  </label>
                </Row>
              )}

              {plan.warnings.length > 0 && (
                <div className="pt-3">
                  <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-300">
                    {plan.warnings.map((w, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </WideModal>
  );
}

export default PartnerPackApplyDialog;
