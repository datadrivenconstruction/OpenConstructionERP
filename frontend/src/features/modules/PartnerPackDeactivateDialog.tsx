// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * PartnerPackDeactivateDialog - the "deactivate this pack" flow with a live
 * progress bar, the mirror of PartnerPackApplyDialog.
 *
 * Deactivating a pack reverses everything activation set up, in three steps the
 * dialog renders as a determinate progress bar + named checklist:
 *
 *   1. Restore and release  - POST /v1/partner-pack/unapply. The backend
 *      re-enables any modules the pack switched off, releases the pack's
 *      projects back into the general workspace (clears the partner_pack tag),
 *      and drops the co-branding.
 *   2. Reset language        - reverts the UI language to English (activation
 *      forced the pack's language, e.g. French for batimatech-ca).
 *   3. Refresh workspace     - re-reads the project list (now un-scoped) and
 *      the active-pack state so the app returns to its vanilla look.
 *
 * The projects and their data are never deleted - only un-associated from the
 * pack - so re-activating the pack later re-scopes the same projects.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  Boxes,
  CheckCircle2,
  FolderOpen,
  Languages,
  Loader2,
  Power,
  RefreshCw,
  XCircle,
} from 'lucide-react';

import { WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { resetPackLocale } from '@/shared/hooks/usePartnerPackLocale';

import { useUnapplyPack } from './partnerPacks';

interface PartnerPackDeactivateDialogProps {
  open: boolean;
  onClose: () => void;
  partnerName: string;
}

type StepKey = 'unapply' | 'language' | 'workspace';
type StepState = 'pending' | 'running' | 'ok' | 'error';

const STEPS: { key: StepKey; labelKey: string; label: string; icon: typeof Boxes }[] = [
  {
    key: 'unapply',
    labelKey: 'modules.pp_deact_unapply',
    label: 'Restore modules and release projects',
    icon: Boxes,
  },
  {
    key: 'language',
    labelKey: 'modules.pp_deact_language',
    label: 'Reset language to English',
    icon: Languages,
  },
  {
    key: 'workspace',
    labelKey: 'modules.pp_deact_workspace',
    label: 'Refresh workspace',
    icon: RefreshCw,
  },
];

function StepGlyph({ state }: { state: StepState }) {
  if (state === 'running') {
    return <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" aria-hidden />;
  }
  if (state === 'ok') {
    return <CheckCircle2 size={16} className="text-semantic-success shrink-0" aria-hidden />;
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

export function PartnerPackDeactivateDialog({
  open,
  onClose,
  partnerName,
}: PartnerPackDeactivateDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const unapply = useUnapplyPack();

  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState<null | { ok: boolean }>(null);
  const [stepStates, setStepStates] = useState<Record<StepKey, StepState>>({
    unapply: 'pending',
    language: 'pending',
    workspace: 'pending',
  });
  const [restored, setRestored] = useState(0);
  const [untagged, setUntagged] = useState(0);

  // Reset when the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setRunning(false);
      setFinished(null);
      setStepStates({ unapply: 'pending', language: 'pending', workspace: 'pending' });
      setRestored(0);
      setUntagged(0);
    }
  }, [open]);

  const completed = useMemo(
    () => STEPS.filter((s) => ['ok', 'error'].includes(stepStates[s.key])).length,
    [stepStates],
  );
  const pct = Math.round((completed / STEPS.length) * 100);

  const setStep = useCallback((key: StepKey, state: StepState) => {
    setStepStates((prev) => ({ ...prev, [key]: state }));
  }, []);

  const handleDeactivate = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setFinished(null);

    // 1. Restore modules + release projects + drop co-branding (real call).
    setStep('unapply', 'running');
    try {
      const res = await unapply.mutateAsync();
      setRestored(res.restored_modules?.length ?? 0);
      setUntagged(res.untagged_projects ?? 0);
      setStep('unapply', 'ok');
    } catch (err) {
      setStep('unapply', 'error');
      setFinished({ ok: false });
      setRunning(false);
      addToast({
        type: 'error',
        title: t('modules.pack_deactivate_failed', { defaultValue: 'Could not deactivate the pack' }),
        message: err instanceof Error ? err.message : undefined,
      });
      return;
    }

    // 2. Reset the UI language to English (activation forced the pack's locale).
    setStep('language', 'running');
    try {
      await resetPackLocale();
    } catch {
      // Non-fatal: the language will fall back to English on next reload.
    }
    setStep('language', 'ok');

    // 3. Refresh the workspace: the project list re-reads un-scoped, and the
    // co-brand hook drops the pack.
    setStep('workspace', 'running');
    void qc.invalidateQueries({ queryKey: ['projects'] });
    // The whole prefix: ['partner-pack', 'current'] never reaches its sibling
    // ['partner-pack', 'installed'], which is the key behind the header chip.
    // Deactivating and leaving the chip standing is the same defect as applying
    // and never raising it.
    void qc.invalidateQueries({ queryKey: ['partner-pack'] });
    void qc.invalidateQueries({ queryKey: ['partner-packs'] });
    void qc.invalidateQueries({ queryKey: ['partner-pack-applied'] });
    void qc.invalidateQueries({ queryKey: ['system-modules'] });
    setStep('workspace', 'ok');

    setFinished({ ok: true });
    setRunning(false);
    addToast({
      type: 'success',
      title: t('modules.pack_deactivated', { defaultValue: 'Pack deactivated' }),
    });
  }, [running, unapply, setStep, addToast, t, qc]);

  const showProgress = running || finished !== null;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="md"
      busy={running}
      title={t('modules.pack_deactivate_title', {
        defaultValue: 'Deactivate {{name}}',
        name: partnerName,
      })}
      subtitle={
        showProgress
          ? t('modules.pp_deact_subtitle_progress', {
              defaultValue: 'Reverting this workspace to its standard setup.',
            })
          : t('modules.pp_deact_subtitle', {
              defaultValue: 'Here is what deactivating this pack will do.',
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
                disabled={running}
                className="rounded-md border border-border bg-surface-primary px-4 py-2 text-sm font-medium text-content-secondary transition hover:bg-surface-secondary disabled:opacity-60"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleDeactivate}
                disabled={running}
                className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {running ? <Loader2 size={15} className="animate-spin" /> : <Power size={15} />}
                {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
              </button>
            </>
          )}
        </div>
      }
    >
      {showProgress ? (
        <div>
          {/* Determinate progress bar. */}
          <div className="mb-1 flex items-center justify-between text-xs font-medium text-content-tertiary">
            <span>
              {finished
                ? t('modules.pp_deact_done_label', { defaultValue: 'Workspace restored' })
                : t('modules.pp_deact_running_label', { defaultValue: 'Deactivating…' })}
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
            {STEPS.map((s) => {
              const state = stepStates[s.key];
              const Icon = s.icon;
              return (
                <li
                  key={s.key}
                  className="flex items-center gap-3 rounded-lg px-2.5 py-2 transition-colors data-[running=true]:bg-oe-blue-subtle/30"
                  data-running={state === 'running'}
                >
                  <Icon
                    size={16}
                    className={state === 'running' ? 'shrink-0 text-oe-blue' : 'shrink-0 text-content-tertiary'}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 text-sm text-content-primary">
                    {t(s.labelKey, { defaultValue: s.label })}
                  </span>
                  <StepGlyph state={state} />
                </li>
              );
            })}
          </ul>

          {/* Success summary. */}
          {finished?.ok && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-semantic-success/40 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-100">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              <span>
                {t('modules.pp_deact_summary', {
                  defaultValue:
                    'Pack deactivated. {{restored}} module(s) restored, {{untagged}} project(s) released back to your workspace.',
                  restored,
                  untagged,
                })}
              </span>
            </div>
          )}
        </div>
      ) : (
        /* ── Intro view: what deactivation does ─────────────────────────── */
        <ul className="space-y-3 text-sm text-content-secondary">
          <li className="flex items-start gap-2.5">
            <Boxes size={16} className="mt-0.5 shrink-0 text-content-tertiary" />
            <span>
              {t('modules.pp_deact_info_modules', {
                defaultValue: 'Restores any modules this pack switched off and removes its co-branding.',
              })}
            </span>
          </li>
          <li className="flex items-start gap-2.5">
            <FolderOpen size={16} className="mt-0.5 shrink-0 text-content-tertiary" />
            <span>
              {t('modules.pp_deact_info_projects', {
                defaultValue:
                  "Releases this pack's projects back into your workspace. Nothing is deleted - your projects and data stay intact.",
              })}
            </span>
          </li>
          <li className="flex items-start gap-2.5">
            <Languages size={16} className="mt-0.5 shrink-0 text-content-tertiary" />
            <span>
              {t('modules.pp_deact_info_language', {
                defaultValue: 'Resets the interface language back to English.',
              })}
            </span>
          </li>
        </ul>
      )}
    </WideModal>
  );
}

export default PartnerPackDeactivateDialog;
