// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * PartnerPackApplyDialog - the "activate this pack" preview + live install.
 *
 * The dialog has three phases:
 *
 *   1. Preview  - a dry-run (`GET /v1/partner-pack/apply-preview/{slug}`) of
 *      exactly what the pack changes (currency, default language, validation
 *      standards, which modules switch on or off, the demo project) and which
 *      of the country's cost databases it can load, each with its size, ticked
 *      by default. Disabling modules is the one destructive effect, so it is
 *      gated behind an explicit opt-in checkbox.
 *
 *   2. Install  - clicking Activate streams the full workspace install
 *      (`POST /v1/partner-pack/full-install-stream`, Server-Sent Events) and
 *      renders a determinate progress bar + a named-step checklist that ticks
 *      over as each step actually runs server-side: apply preset, install
 *      language, load the work catalog, its resources and its resource
 *      catalogue, create the demo projects.
 *
 *   3. Result   - one line per step saying what it did: the language the
 *      interface is actually in now, each cost base with its item count or
 *      the reason it did not load, the catalogue, the demos, the validation
 *      rule sets. A failed step gets its own retry.
 *
 * An install that fails as a whole (the server refuses it, the network drops,
 * the stream is cut) ends on a failure panel that says what failed and why.
 * It used to end on "Finished with warnings" over an empty checklist, which is
 * all a viewer account saw after a 403.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import i18n, { loadLocaleResource, normalizePackLocale, SUPPORTED_LANGUAGES } from '@/app/i18n';
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
  Library,
  Loader2,
  MinusCircle,
  Package,
  Power,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { WideModal, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';

import { canInstallPacks, useApplyPreview, type PackCostBase } from './partnerPacks';
import {
  fullInstallPackStream,
  PackInstallError,
  type FullInstallStepStatus,
  type PackInstallFailureKind,
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
  catalog: Library,
  vector_db: Boxes,
  demos: FolderOpen,
};

/** Per-step UI state while/after the streamed install runs. */
type StepUiState = 'pending' | 'running' | FullInstallStepStatus;

/** An install that failed as a whole, before or during the stream. */
interface InstallFailure {
  kind: PackInstallFailureKind;
  status: number | null;
  detail: string | null;
  /** True when the failure came after the checklist had started. */
  midStream: boolean;
}

/** What the language step actually left on screen, read back after the switch. */
interface LanguageResult {
  /** The pack's language, normalized to a bundle we ship. */
  target: string;
  /** ``i18n.language`` after the switch attempt. */
  current: string;
  outcome: 'switched' | 'already' | 'kept' | 'failed';
}

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

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((v): v is Record<string, unknown> => !!v && typeof v === 'object')
    : [];
}

/** The language's own name from the list we ship, or the code. */
function languageName(code: string): string {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code)?.name ?? code;
}

/**
 * A cost base's country in the reader's language, from its ISO flag code.
 * The registry's ``market`` label is English and stays the fallback.
 */
function baseCountry(flag: string | null | undefined, market: string | null | undefined): string {
  if (flag && /^[a-z]{2}$/i.test(flag)) {
    try {
      const name = new Intl.DisplayNames([i18n.language || 'en'], { type: 'region' }).of(
        flag.toUpperCase(),
      );
      if (name) return name;
    } catch {
      // Intl.DisplayNames missing or the code unknown: fall through.
    }
  }
  return market ?? '';
}

/** Where someone who may only view packs can get a copy they administer. */
export const PACK_INSTALL_DOWNLOAD_URL = 'https://openconstructionerp.com/download';

/**
 * The second half of "this account may not install packs": where to go
 * instead. The public demo keeps its accounts read-only on purpose, so for
 * most readers of that message the answer is their own installation, where
 * they are the administrator.
 */
export function PackOwnCopyHint() {
  const { t } = useTranslation();
  return (
    <span className="mt-1 block">
      {t('modules.pp_own_copy_hint', {
        defaultValue: 'To install packs, run the platform yourself: in your own copy you are the administrator.',
      })}{' '}
      <a
        href={PACK_INSTALL_DOWNLOAD_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium underline"
      >
        {t('modules.pp_own_copy_link', { defaultValue: 'Download and install guide' })}
      </a>
    </span>
  );
}

export function PartnerPackApplyDialog({
  open,
  onClose,
  slug,
  partnerName,
}: PartnerPackApplyDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const canInstall = canInstallPacks(useAuthStore((s) => s.userRole));
  const qc = useQueryClient();

  const { data: preview, isLoading, isError } = useApplyPreview(open ? slug : null);

  const [confirmDisables, setConfirmDisables] = useState(false);
  const [installDemo, setInstallDemo] = useState(true);
  const [selectedBases, setSelectedBases] = useState<Set<string>>(new Set());
  const [installCatalog, setInstallCatalog] = useState(true);

  // Install phase state.
  const [installing, setInstalling] = useState(false);
  const [finished, setFinished] = useState<null | { ok: boolean }>(null);
  const [failure, setFailure] = useState<InstallFailure | null>(null);
  const [steps, setSteps] = useState<StreamStepDescriptor[]>([]);
  const [stepStates, setStepStates] = useState<Record<string, StepUiState>>({});
  const [stepDetail, setStepDetail] = useState<Record<string, Record<string, unknown>>>({});
  const [language, setLanguage] = useState<LanguageResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // A retry streams a narrower ``start`` frame. It must refresh the rows it
  // reruns, not replace the checklist with them.
  const retryRef = useRef(false);
  // The step states as the last event left them, readable without waiting for
  // a render. The verdict after a retry is read from here: the retry's own
  // ``done.ok`` covers only the rows it reran. Every write goes through
  // ``putStates`` so the ref and the rendered rows never disagree.
  const statesRef = useRef<Record<string, StepUiState>>({});
  const putStates = useCallback((next: Record<string, StepUiState>) => {
    statesRef.current = next;
    setStepStates(next);
  }, []);

  // Reset everything whenever the dialog (re)opens for a (possibly different) pack.
  useEffect(() => {
    if (open) {
      setConfirmDisables(false);
      setInstallDemo(true);
      setInstallCatalog(true);
      setInstalling(false);
      setFinished(null);
      setFailure(null);
      setSteps([]);
      putStates({});
      setStepDetail({});
      setLanguage(null);
    } else {
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open, slug, putStates]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const plan = preview?.plan;
  const willDisable = (plan?.modules_to_disable.length ?? 0) > 0;
  const costBases: PackCostBase[] | null = plan?.cost_bases ?? null;
  const loadableBases = useMemo(() => (costBases ?? []).filter((b) => b.loadable), [costBases]);

  // Every loadable base starts ticked; the user unticks what they do not want.
  useEffect(() => {
    setSelectedBases(new Set(loadableBases.map((b) => b.slug)));
  }, [loadableBases]);

  const selectedHaveCatalog = loadableBases.some((b) => selectedBases.has(b.slug) && b.has_catalog);

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
      if (step === 'resources' || step === 'catalog') {
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

  const handleEvent = useCallback((evt: StreamInstallEvent) => {
    let next: Record<string, StepUiState> | null = null;
    if (evt.type === 'start') {
      if (retryRef.current) {
        next = { ...statesRef.current };
        for (const s of evt.steps) next[s.step] = 'pending';
      } else {
        setSteps(evt.steps);
        next = {};
        for (const s of evt.steps) next[s.step] = 'pending';
      }
    } else if (evt.type === 'step_start') {
      next = { ...statesRef.current, [evt.step]: 'running' };
    } else if (evt.type === 'step_done') {
      next = { ...statesRef.current, [evt.step]: evt.status };
      setStepDetail((prev) => ({ ...prev, [evt.step]: evt.detail }));
    }
    if (next) putStates(next);
    // ``done`` is handled by the awaiting caller (it carries the overall ok).
  }, [putStates]);

  /**
   * Switch the interface to the pack's language and read back what stuck.
   *
   * The usePartnerPackLocale hook in AppLayout also does this once the pack
   * query refetches, but that is asynchronous and says nothing to the user.
   * Doing it here, awaited, lets the result line state the language the
   * interface is actually in rather than the one it was asked to be in.
   * English packs do not force English on a reader who chose another
   * language, the same rule the hook follows.
   */
  const applyLanguage = useCallback(
    async (rawLocale: string | null) => {
      if (!rawLocale) return;
      const target = normalizePackLocale(rawLocale);
      const before = i18n.language;
      if (target === before) {
        setLanguage({ target, current: before, outcome: 'already' });
        return;
      }
      if (target === 'en') {
        setLanguage({ target, current: before, outcome: 'kept' });
        return;
      }
      try {
        try {
          window.localStorage.setItem('oce-pack-locale-active', slug);
          window.localStorage.setItem('i18nextLng', target);
        } catch {
          /* localStorage unavailable */
        }
        await loadLocaleResource(target);
        await i18n.changeLanguage(target);
      } catch {
        // A chunk that failed to load leaves the language where it was; the
        // check below reports that instead of claiming the switch.
      }
      const after = i18n.language;
      setLanguage({ target, current: after, outcome: after === target ? 'switched' : 'failed' });
    },
    [slug],
  );

  const runInstall = useCallback(
    async (onlySteps?: StreamStepName[]) => {
      if (installing || !canInstall) return;
      const isRetry = onlySteps !== undefined;
      retryRef.current = isRetry;
      setInstalling(true);
      setFinished(null);
      setFailure(null);
      if (!isRetry) {
        setSteps([]);
        putStates({});
        setStepDetail({});
        setLanguage(null);
      }
      const controller = new AbortController();
      abortRef.current = controller;

      let ok = false;
      let sawStart = isRetry;
      let applyOk = false;
      let packLocale: string | null = plan?.default_locale ?? null;
      try {
        await fullInstallPackStream(
          slug,
          (evt) => {
            handleEvent(evt);
            if (evt.type === 'start') sawStart = true;
            if (evt.type === 'step_done' && evt.step === 'apply_pack') applyOk = evt.status === 'ok';
            if (evt.type === 'step_done' && evt.step === 'locale') {
              packLocale = asString(evt.detail.locale) ?? packLocale;
            }
            if (evt.type === 'done') ok = evt.ok;
          },
          {
            demoCount: installDemo ? 2 : 0,
            confirmDisables,
            // An older backend sends no cost_bases; leave the choice to it.
            costRegions: costBases ? Array.from(selectedBases) : undefined,
            installCatalog: installCatalog && selectedHaveCatalog,
            onlySteps,
            signal: controller.signal,
          },
        );
        // A retry's ``done.ok`` speaks for the rows it reran only; the
        // install as a whole is ok when every row of the checklist finished.
        if (isRetry) ok = Object.values(statesRef.current).every((st) => st === 'ok' || st === 'skipped');
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
        void qc.invalidateQueries({ queryKey: ['system-modules'] });
        // The backend hides other-pack projects from the listing the instant a
        // pack is applied, so drop the cached project list to make the updated
        // view appear immediately (mirrors deactivation).
        void qc.invalidateQueries({ queryKey: ['projects'] });
        // Cost bases and catalogue rows just changed under the cost pages.
        void qc.invalidateQueries({ queryKey: ['costs'] });
        void qc.invalidateQueries({ queryKey: ['catalog'] });
        // The pack is applied once its first step is, whatever the later steps
        // did, so its language follows even when a cost base failed.
        if (applyOk) await applyLanguage(packLocale);
        if (ok) {
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
        if ((err as { name?: string })?.name === 'AbortError') {
          setFinished({ ok: false });
          return;
        }
        const next: InstallFailure =
          err instanceof PackInstallError
            ? { kind: err.kind, status: err.status, detail: err.detail, midStream: sawStart }
            : { kind: 'network', status: null, detail: null, midStream: sawStart };
        setFailure(next);
        // Mark any still-running step as errored so nothing spins.
        const swept = { ...statesRef.current };
        for (const k of Object.keys(swept)) {
          if (swept[k] === 'running' || swept[k] === 'pending') swept[k] = 'error';
        }
        putStates(swept);
        setFinished({ ok: false });
        if (applyOk) await applyLanguage(packLocale);
        addToast({
          type: 'error',
          title: t('modules.pack_apply_failed', { defaultValue: 'Could not activate this pack' }),
          message: failureTitle(next.kind),
        });
      } finally {
        setInstalling(false);
        abortRef.current = null;
        retryRef.current = false;
      }
    },
    // ``failureTitle`` is a hoisted declaration of this render that reads
    // only ``t``, which is listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      installing,
      canInstall,
      slug,
      installDemo,
      confirmDisables,
      costBases,
      selectedBases,
      installCatalog,
      selectedHaveCatalog,
      plan?.default_locale,
      handleEvent,
      putStates,
      applyLanguage,
      qc,
      addToast,
      t,
      partnerName,
    ],
  );

  /** Headline for a whole-install failure, one literal key per kind. */
  function failureTitle(kind: PackInstallFailureKind): string {
    switch (kind) {
      case 'forbidden':
        return t('modules.pp_fail_forbidden_title', {
          defaultValue: 'This account may not install packs',
        });
      case 'unauthenticated':
        return t('modules.pp_fail_auth_title', { defaultValue: 'Your session has ended' });
      case 'not_found':
        return t('modules.pp_fail_not_found_title', {
          defaultValue: 'This pack is no longer on the server',
        });
      case 'conflict':
        return t('modules.pp_fail_conflict_title', {
          defaultValue: 'The pack cannot be applied as it is',
        });
      case 'invalid':
        return t('modules.pp_fail_invalid_title', {
          defaultValue: 'The server rejected the install request',
        });
      case 'server':
        return t('modules.pp_fail_server_title', {
          defaultValue: 'The server failed while installing the pack',
        });
      case 'network':
        return t('modules.pp_fail_network_title', { defaultValue: 'Could not reach the server' });
      case 'incomplete':
        return t('modules.pp_fail_incomplete_title', {
          defaultValue: 'The connection dropped during the installation',
        });
      default:
        return t('modules.pp_fail_http_title', {
          defaultValue: 'The installation could not start',
        });
    }
  }

  /** What to do about a whole-install failure, one literal key per kind. */
  function failureBody(kind: PackInstallFailureKind): string {
    switch (kind) {
      case 'forbidden':
        return t('modules.pp_fail_forbidden_body', {
          defaultValue:
            'Installing a pack changes language, currency, modules and cost data for everyone in this workspace, so it needs an administrator. Ask an administrator to install it. Nothing was changed.',
        });
      case 'unauthenticated':
        return t('modules.pp_fail_auth_body', {
          defaultValue: 'Sign in again, then start the installation again. Nothing was changed.',
        });
      case 'not_found':
        return t('modules.pp_fail_not_found_body', {
          defaultValue: 'Rescan the packs or upload this pack again, then retry.',
        });
      case 'conflict':
        return t('modules.pp_fail_conflict_body', {
          defaultValue:
            'The server found a problem in the pack itself. The reason is below; the pack has to be corrected before it can be installed.',
        });
      case 'invalid':
        return t('modules.pp_fail_invalid_body', {
          defaultValue: 'The request was not accepted. The reason is below.',
        });
      case 'server':
        return t('modules.pp_fail_server_body', {
          defaultValue:
            'Nothing is confirmed as installed. Try again; if it fails again, the server log holds the cause.',
        });
      case 'network':
        return t('modules.pp_fail_network_body', {
          defaultValue: 'Check the connection and try again. Nothing was confirmed as installed.',
        });
      case 'incomplete':
        return t('modules.pp_fail_incomplete_body', {
          defaultValue:
            'Steps that finished are kept. Try again to finish the rest; bases already loaded are not loaded twice.',
        });
      default:
        return t('modules.pp_fail_http_body', {
          defaultValue: 'The server did not accept the request. The reason is below.',
        });
    }
  }

  /** A skipped or failed step's reason, from the backend's reason code. */
  function reasonText(code: string | null, fallback: string | null): string | null {
    switch (code) {
      case 'no_published_base':
        return t('modules.pp_reason_no_published_base', {
          defaultValue: 'no cost database is published for this region yet',
        });
      case 'duplicate_base':
        return t('modules.pp_reason_duplicate_base', {
          defaultValue: 'the same database as another region of this pack',
        });
      case 'not_selected':
        return t('modules.pp_reason_not_selected', { defaultValue: 'not selected' });
      case 'none_selected':
        return t('modules.pp_reason_none_selected', {
          defaultValue: 'no cost database was selected',
        });
      case 'no_loadable_base':
        return t('modules.pp_reason_no_loadable_base', {
          defaultValue: 'no cost database is published for this country yet',
        });
      case 'no_regions_declared':
        return t('modules.pp_reason_no_regions', {
          defaultValue: 'this pack ships no cost database',
        });
      case 'no_cost_db':
        return t('modules.pp_reason_no_cost_db', { defaultValue: 'no cost database was loaded' });
      case 'no_catalog':
        return t('modules.pp_reason_no_catalog', {
          defaultValue: 'no resource catalogue is published for these databases',
        });
      case 'not_requested':
        return t('modules.pp_reason_not_requested', { defaultValue: 'not requested' });
      case 'no_demos_mapped':
        return t('modules.pp_reason_no_demos', {
          defaultValue: 'this pack has no sample project',
        });
      case 'no_default_locale':
        return t('modules.pp_reason_no_locale', { defaultValue: 'the pack sets no language' });
      default:
        return fallback;
    }
  }

  const fmt = (n: number) => n.toLocaleString(getNumberLocale());

  /** One or more lines describing what a finished step did. */
  function resultLines(step: StreamStepName): string[] {
    const d = stepDetail[step] ?? {};
    const state = stepStates[step];
    const error = asString(d.error);
    if (state === 'error' && error && step !== 'cost_db' && step !== 'catalog') {
      return [t('modules.pp_result_error', { defaultValue: 'Failed: {{reason}}', reason: error })];
    }
    const reason = reasonText(asString(d.reason_code), asString(d.reason));
    switch (step) {
      case 'apply_pack': {
        if (state !== 'ok') {
          return [t('modules.pp_result_apply_failed', { defaultValue: 'The pack was not applied.' })];
        }
        const lines = [
          t('modules.pp_result_applied', {
            defaultValue: '{{name}} is the active pack.',
            name: partnerName,
          }),
        ];
        const rules = Array.isArray(d.rule_sets) ? (d.rule_sets as unknown[]).map(String) : [];
        lines.push(
          rules.length > 0
            ? t('modules.pp_result_rules', {
                defaultValue: 'Validation rules switched on for new projects: {{rules}}',
                rules: fmtList(rules),
              })
            : t('modules.pp_result_rules_none', {
                defaultValue: 'No extra validation rule sets; the standard checks stay on.',
              }),
        );
        return lines;
      }
      case 'locale': {
        if (!language) {
          return state === 'skipped' && reason ? [reason] : [];
        }
        const target = languageName(language.target);
        const current = languageName(language.current);
        if (language.outcome === 'switched' || language.outcome === 'already') {
          return [
            t('modules.pp_result_lang_on', {
              defaultValue: 'The interface is in {{language}}.',
              language: current,
            }),
          ];
        }
        if (language.outcome === 'kept') {
          return [
            t('modules.pp_result_lang_kept', {
              defaultValue:
                'The pack works in {{pack}}; the interface stays in {{language}}, the language you chose.',
              pack: target,
              language: current,
            }),
          ];
        }
        return [
          t('modules.pp_result_lang_failed', {
            defaultValue:
              'Could not switch the interface to {{pack}}; it is still in {{language}}. Choose the language in the header menu.',
            pack: target,
            language: current,
          }),
        ];
      }
      case 'cost_db': {
        const bases = asRecords(d.bases);
        if (bases.length === 0) return reason ? [reason] : [];
        return bases.map((b) => {
          const name = asString(b.db_id) ?? asString(b.slug) ?? '';
          const status = asString(b.status);
          if (status === 'ok') {
            return b.already_loaded
              ? t('modules.pp_result_base_present', {
                  defaultValue: '{{base}}: already loaded, {{items}} work items',
                  base: name,
                  items: fmt(asCount(b.items) ?? 0),
                })
              : t('modules.pp_result_base_loaded', {
                  defaultValue: '{{base}}: {{items}} work items loaded',
                  base: name,
                  items: fmt(asCount(b.items) ?? 0),
                });
          }
          if (status === 'error') {
            return t('modules.pp_result_base_failed', {
              defaultValue: '{{base}}: not loaded, {{reason}}',
              base: name,
              reason: asString(b.error) ?? '',
            });
          }
          return t('modules.pp_result_base_skipped', {
            defaultValue: '{{base}}: skipped, {{reason}}',
            base: name,
            reason: reasonText(asString(b.reason_code), null) ?? '',
          });
        });
      }
      case 'resources': {
        const n = asCount(d.resources) ?? 0;
        if (state === 'ok') {
          return [
            t('modules.pp_result_resources', {
              defaultValue: 'Labour, material and equipment lines inside the work items: {{resources}}',
              resources: fmt(n),
            }),
          ];
        }
        return reason ? [reason] : [];
      }
      case 'catalog': {
        const catalogs = asRecords(d.catalogs);
        if (catalogs.length === 0) return reason ? [reason] : [];
        return catalogs.map((c) => {
          const name = asString(c.db_id) ?? '';
          const status = asString(c.status);
          if (status === 'ok') {
            return c.already_loaded
              ? t('modules.pp_result_catalog_present', {
                  defaultValue: 'Resource catalogue {{base}}: already loaded, {{resources}} resources',
                  base: name,
                  resources: fmt(asCount(c.resources) ?? 0),
                })
              : t('modules.pp_result_catalog_loaded', {
                  defaultValue: 'Resource catalogue {{base}}: {{resources}} resources loaded',
                  base: name,
                  resources: fmt(asCount(c.resources) ?? 0),
                });
          }
          if (status === 'error') {
            return t('modules.pp_result_catalog_failed', {
              defaultValue: 'Resource catalogue {{base}}: not loaded, {{reason}}',
              base: name,
              reason: asString(c.error) ?? '',
            });
          }
          return t('modules.pp_result_catalog_skipped', {
            defaultValue: 'Resource catalogue {{base}}: skipped, {{reason}}',
            base: name,
            reason: reasonText(asString(c.reason_code), null) ?? '',
          });
        });
      }
      case 'demos': {
        const installed = Array.isArray(d.installed) ? d.installed.length : 0;
        if (installed > 0) {
          return [
            t('modules.pp_result_demos', {
              defaultValue: 'Sample projects created: {{projects}}',
              projects: fmt(installed),
            }),
          ];
        }
        return reason ? [reason] : [];
      }
      default:
        return reason ? [reason] : [];
    }
  }

  const showProgress = installing || finished !== null;
  const failedBeforeStart = failure !== null && !failure.midStream;
  const failedSteps = steps.filter((s) => stepStates[s.step] === 'error').map((s) => s.step);

  /** Rerun one failed step. A failed apply means the whole install again. */
  function retryStep(step: StreamStepName) {
    if (step === 'apply_pack') {
      void runInstall();
      return;
    }
    if (step === 'locale') {
      void applyLanguage(asString(stepDetail.locale?.locale) ?? plan?.default_locale ?? null);
      return;
    }
    void runInstall([step]);
  }

  const failurePanel = failure && (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-lg border border-semantic-error/40 bg-red-50 px-3.5 py-3 text-sm text-red-900 dark:bg-red-900/20 dark:text-red-100"
    >
      {failure.kind === 'forbidden' ? (
        <ShieldAlert size={18} className="mt-0.5 shrink-0" aria-hidden />
      ) : (
        <XCircle size={18} className="mt-0.5 shrink-0" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{failureTitle(failure.kind)}</p>
        <p className="mt-1">{failureBody(failure.kind)}</p>
        {failure.kind === 'forbidden' && <PackOwnCopyHint />}
        {failure.detail && (
          <p className="mt-1.5 break-words text-xs opacity-80">
            {t('modules.pp_fail_server_said', {
              defaultValue: 'Server response: {{detail}}',
              detail: failure.detail,
            })}
          </p>
        )}
        {failure.status != null && (
          <p className="mt-0.5 text-2xs opacity-70">HTTP {failure.status}</p>
        )}
      </div>
    </div>
  );

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
            <>
              {failedBeforeStart && failure?.kind !== 'forbidden' && (
                <button
                  type="button"
                  onClick={() => void runInstall()}
                  disabled={installing}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-primary px-4 py-2 text-sm font-medium text-content-secondary transition hover:bg-surface-secondary disabled:opacity-60"
                >
                  <RotateCcw size={14} />
                  {t('modules.pp_try_again', { defaultValue: 'Try again' })}
                </button>
              )}
              <button
                type="button"
                onClick={onClose}
                disabled={installing}
                className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-oe-blue/90 disabled:opacity-60"
              >
                {failedBeforeStart
                  ? t('common.close', { defaultValue: 'Close' })
                  : t('common.done', { defaultValue: 'Done' })}
              </button>
            </>
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
                onClick={() => void runInstall()}
                disabled={installing || isLoading || isError || showProgress || !canInstall}
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
      {/* ── Whole-install failure before any step ran ─────────────────────── */}
      {showProgress && failedBeforeStart ? (
        failurePanel
      ) : showProgress ? (
        <div>
          {failure && <div className="mb-4">{failurePanel}</div>}

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

          {/* Step checklist; once finished, each row says what it did. */}
          <ul className="mt-4 space-y-1.5" data-testid="pack-install-steps">
            {steps.map((s) => {
              const state = stepStates[s.step] ?? 'pending';
              const Icon = STEP_ICONS[s.step] ?? Package;
              const caption = stepCaption(s.step);
              const lines = finished ? resultLines(s.step) : [];
              return (
                <li
                  key={s.step}
                  className="rounded-lg px-2.5 py-2 transition-colors data-[running=true]:bg-oe-blue-subtle/30"
                  data-running={state === 'running'}
                  data-step={s.step}
                  data-state={state}
                >
                  <div className="flex items-center gap-3">
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
                    {finished && state === 'error' && (
                      <button
                        type="button"
                        onClick={() => retryStep(s.step)}
                        disabled={installing}
                        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium text-content-secondary transition hover:bg-surface-secondary disabled:opacity-60"
                      >
                        <RotateCcw size={12} />
                        {t('modules.pp_retry_step', { defaultValue: 'Retry' })}
                      </button>
                    )}
                    <StepGlyph state={state} />
                  </div>
                  {lines.length > 0 && (
                    <ul className="ms-7 mt-1 space-y-0.5 text-xs text-content-secondary">
                      {lines.map((line, i) => (
                        <li key={i} className="break-words">
                          {line}
                        </li>
                      ))}
                    </ul>
                  )}
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
                  ? t('modules.pp_summary_ready', {
                      defaultValue: 'Everything above is installed and ready to use.',
                    })
                  : failedSteps.length > 0
                    ? t('modules.pp_summary_failed_steps', {
                        defaultValue:
                          'Some steps failed: {{steps}}. Completed steps are kept; use Retry next to a failed step.',
                        steps: fmtList(
                          steps.filter((s) => failedSteps.includes(s.step)).map((s) => stepLabel(s)),
                        ),
                      })
                    : t('modules.pp_summary_stopped', {
                        defaultValue: 'The installation stopped before it finished.',
                      })}
              </span>
            </div>
          )}
        </div>
      ) : (
        <>
          {/* ── Preview view ────────────────────────────────────────────────── */}
          {!canInstall && (
            <div
              role="note"
              className="mb-3 flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-amber-50 px-3.5 py-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-100"
            >
              <ShieldAlert size={16} className="mt-0.5 shrink-0" />
              <span>
                {t('modules.pack_admin_only_hint', {
                  defaultValue:
                    'Only an administrator can activate a pack. You can review what it contains here.',
                })}
                <PackOwnCopyHint />
              </span>
            </div>
          )}

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

              {/* The country's cost databases, offered before anything loads. */}
              <Row
                icon={<Database size={15} />}
                label={t('modules.pack_data', { defaultValue: 'Cost data installed' })}
              >
                {costBases ? (
                  costBases.length === 0 || loadableBases.length === 0 ? (
                    <div className="space-y-1.5">
                      <p className="text-amber-700 dark:text-amber-300" data-testid="pack-no-cost-base">
                        {t('modules.pp_data_no_base', {
                          defaultValue:
                            'No cost database is published for this country yet. The pack sets language, currency and rules; a cost database can be imported later under Cost databases.',
                        })}
                      </p>
                      {costBases.length > 0 && (
                        <ul className="space-y-0.5 text-xs text-content-tertiary">
                          {costBases.map((b) => (
                            <li key={b.slug}>
                              {b.slug}: {reasonText(b.reason_code, null)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-1.5" data-testid="pack-cost-bases">
                      {costBases.map((b) =>
                        b.loadable ? (
                          <label
                            key={b.slug}
                            className="flex cursor-pointer items-start gap-2 rounded-md px-1 py-0.5 hover:bg-surface-secondary"
                          >
                            <input
                              type="checkbox"
                              className="mt-1"
                              checked={selectedBases.has(b.slug)}
                              onChange={(e) =>
                                setSelectedBases((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) next.add(b.slug);
                                  else next.delete(b.slug);
                                  return next;
                                })
                              }
                            />
                            <span className="min-w-0">
                              <span className="font-medium text-content-primary">
                                {baseCountry(b.flag, b.market)}
                              </span>
                              <span className="ms-1.5 font-mono text-xs text-content-tertiary">
                                {b.db_id}
                              </span>
                              <span className="block text-xs text-content-tertiary">
                                {t('modules.pp_base_size', {
                                  defaultValue: '{{items}} work items in {{currency}}',
                                  items: fmt(b.positions ?? 0),
                                  currency: b.currency ?? '',
                                })}
                                {b.has_catalog &&
                                  ` · ${t('modules.pp_base_has_catalog', {
                                    defaultValue: 'resource catalogue available',
                                  })}`}
                              </span>
                            </span>
                          </label>
                        ) : (
                          <p key={b.slug} className="px-1 text-xs text-content-tertiary">
                            {b.slug}: {reasonText(b.reason_code, null)}
                          </p>
                        ),
                      )}
                      {selectedBases.size === 0 && (
                        <p className="px-1 text-xs text-amber-700 dark:text-amber-300">
                          {t('modules.pp_data_none_selected', {
                            defaultValue:
                              'No cost database selected. The pack will be applied without cost data.',
                          })}
                        </p>
                      )}
                      {loadableBases.some((b) => b.has_catalog) && (
                        <label className="mt-1 flex cursor-pointer items-center gap-2 px-1 text-sm">
                          <input
                            type="checkbox"
                            checked={installCatalog}
                            disabled={!selectedHaveCatalog}
                            onChange={(e) => setInstallCatalog(e.target.checked)}
                          />
                          <span>
                            {t('modules.pp_install_catalog', {
                              defaultValue: 'Also load the resource catalogue for the selected databases',
                            })}
                          </span>
                        </label>
                      )}
                    </div>
                  )
                ) : plan.cwicr_regions.length > 0 ? (
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
