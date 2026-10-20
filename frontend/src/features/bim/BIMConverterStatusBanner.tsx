// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMConverterStatusBanner — always-visible health panel for the four DDC
 * converters needed by the BIM Hub drag-and-drop (.rvt / .ifc) and DWG Takeoff (.dwg).
 *
 * v2.6.23 architecture: the banner is the single source of truth for
 * converter state on /bim. It does three things the previous version did
 * not:
 *  1. Includes IFC (the "Revit and IFC don't load" complaint was rooted
 *     in IFC never being surfaced — the install button was unreachable).
 *  2. Stays visible even when everything is healthy, so the user can
 *     verify rather than guess.
 *  3. Can smoke-test each installed converter (`verify=true`, an 8 s run
 *     per binary server-side). A binary that exists on disk but cannot
 *     load (Qt6 DLL missing, Mark-of-the-Web, VCRedist absent) shows up
 *     here as ⚠ Failed, with the specific reason and one-click fix
 *     buttons mapped from the backend's `suggested_actions`.
 *
 * The smoke test is not automatic. Since #416 the panel lists converters
 * on mount and runs nothing: it renders on /bim, /projects and /settings,
 * and executing every installed converter because a page opened is how a
 * converter that cannot start became a page-opening error. Installed rows
 * read "Installed" (neutral) until the user presses Check now, a row's
 * Re-check, or installs something - after which this panel keeps
 * verifying for the rest of its life.
 *
 * Cache: shares the `['bim-converters']` React-Query key with the upload
 * preflight in BIMPage so an install / verify here invalidates both.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  ShieldAlert,
  X,
  XCircle,
} from 'lucide-react';

import {
  fetchBIMConverters,
  fetchConverterVersionCheck,
  installBIMConverter,
  verifyBIMConverter,
  type BIMConverterAction,
  type BIMConverterHealth,
  type BIMConverterInfo,
  type BIMConvertersResponse,
  type ConverterVersionCheck,
} from './api';
import { ConverterInstallProgressBar } from './ConverterInstallProgressBar';
import { converterName, converterPlatformMessage, converterVersionLabel } from './converterText';
import { useToastStore } from '@/stores/useToastStore';

/** Ids of converters surfaced on the BIM page. IFC was previously missing
 *  here — that's why "Revit and IFC don't load" was reported as a bug.
 *  Note: ``dwg`` covers .dxf, ``ifc`` covers .ifczip. Formats accepted by
 *  ``upload-cad`` but without a dedicated converter (.fbx/.obj/.3ds) are
 *  noted in the banner subtitle rather than rendered as fake chips —
 *  there is no separate binary to install for those. */
const PANEL_CONVERTER_IDS = ['rvt', 'ifc', 'dwg'] as const;

/** Converter ids that have a built-in fallback parser in the backend. The
 *  IFC text-parser at ``ifc_processor.py`` produces 2D placeholder
 *  geometry without DDC, so users see a working — if approximate —
 *  model even when the binary is not installed. The banner annotates
 *  these rows with a green "Works without DDC (fallback)" badge so the
 *  user does not interpret "0/4 installed" as "0/4 functional". */
const CONVERTERS_WITH_FALLBACK = new Set<string>(['ifc']);

/** GitHub root for the manual-install fallback links. */
const DDC_REPO_URL =
  'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG/releases/tag/v2026.10.0';

const VC_REDIST_URL =
  'https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist';

interface BIMConverterStatusBannerProps {
  className?: string;
  /** When true, render an "X" close button. Dismissed state is persisted
   *  in localStorage so the banner doesn't reappear on every navigation
   *  once the user has acknowledged it. The Dashboard / Projects empty
   *  state passes `dismissible={true}` so it stays out of the way once
   *  things are healthy; the dedicated /bim page omits it. */
  dismissible?: boolean;
  /** When true, the page already has at least one ``status="ready"`` model
   *  loaded — the user is past the install-required gate. The banner
   *  starts collapsed in this case so the 3D scene is not pushed below
   *  the fold by an install nag the user can no longer act on. */
  defaultCollapsed?: boolean;
}

export function BIMConverterStatusBanner({
  className,
  dismissible = false,
  defaultCollapsed = false,
}: BIMConverterStatusBannerProps): JSX.Element | null {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('oe_bim_converter_panel_dismissed') === '1';
    } catch {
      return false;
    }
  });
  // The upstream-version signature in effect when the user last pressed
  // the panel "X". Persisted so a dismissal survives reloads, but is
  // scoped to that specific set of converter builds: when DDC ships a
  // *newer* version the signature changes and the dismissal auto-expires,
  // so the user still learns about future updates instead of an "X" click
  // silencing the panel forever (the original bug — see notes below).
  const [dismissedVersionSig, setDismissedVersionSig] = useState<string>(
    () => {
      try {
        return (
          localStorage.getItem('oe_bim_converter_panel_dismissed_sig') ?? ''
        );
      } catch {
        return '';
      }
    },
  );
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const persisted = localStorage.getItem('oe_bim_converter_panel_collapsed');
      if (persisted === '1') return true;
      if (persisted === '0') return false;
      // No explicit user choice yet — fall back to the page-level hint
      // (``defaultCollapsed=true`` when at least one ready model is loaded).
      return defaultCollapsed;
    } catch {
      return defaultCollapsed;
    }
  });

  // The "new version available" banner uses sessionStorage so it auto-clears
  // when the user closes the tab — i.e. it shows up again on every fresh
  // visit/reload, but a one-time "X" press keeps it hidden for the rest of
  // the working session. This matches the user's spec ("can be hidden once
  // when opening the project — but let it appear each time").
  const [updateBannerDismissed, setUpdateBannerDismissed] = useState<boolean>(
    () => {
      try {
        return sessionStorage.getItem('oe_bim_converter_update_banner_dismissed') === '1';
      } catch {
        return false;
      }
    },
  );

  const setUpdateBannerDismissedSession = (val: boolean): void => {
    setUpdateBannerDismissed(val);
    try {
      sessionStorage.setItem(
        'oe_bim_converter_update_banner_dismissed',
        val ? '1' : '0',
      );
    } catch {
      /* storage unavailable */
    }
  };

  // True while a dismissal was recorded before the version-check query had
  // resolved (collapsed strip / mini-icon X, or the X pressed during the
  // brief post-mount window). The reconciliation effect below backfills the
  // real signature once it is known so the dismissal is correctly scoped to
  // the update the user actually saw — instead of expiring the instant the
  // SHA arrives (the original "reappears forever" bug).
  const dismissedBeforeSigKnown = useRef<boolean>(false);

  const setDismissedPersist = (
    val: boolean,
    versionSig = '',
    sigResolved = true,
  ): void => {
    setDismissed(val);
    setDismissedVersionSig(val ? versionSig : '');
    dismissedBeforeSigKnown.current = val ? !sigResolved : false;
    try {
      localStorage.setItem(
        'oe_bim_converter_panel_dismissed',
        val ? '1' : '0',
      );
      localStorage.setItem(
        'oe_bim_converter_panel_dismissed_sig',
        val ? versionSig : '',
      );
    } catch {
      /* storage unavailable */
    }
  };

  const setCollapsedPersist = (val: boolean): void => {
    setCollapsed(val);
    try {
      localStorage.setItem(
        'oe_bim_converter_panel_collapsed',
        val ? '1' : '0',
      );
    } catch {
      /* storage unavailable */
    }
  };

  // `verify=true` makes the server spawn every installed converter
  // executable to smoke-test it, 8 s timeout each. Mounting this banner is
  // not a reason to do that: it renders on /bim, /projects and /settings, so
  // simply arriving at one of those pages ran every converter with no file
  // to convert - which is how the reporter of #416 met a Windows loader
  // error. The passive listing (installed, missing, size, upstream version)
  // needs no execution at all, so that is what the automatic fetch asks for,
  // and installed converters come back as `unknown` until somebody checks.
  //
  // A ref, not state, so the queryFn reads the current choice when it runs
  // and a `refetch()` in the same tick already carries it. Once the user has
  // asked for a check - the header button, a row's Re-check, or an install -
  // it stays on for the life of this panel, otherwise the invalidation those
  // actions trigger would immediately refetch without verify and throw away
  // the verdict the user just asked for. The backend caches health for five
  // minutes, so what that costs is bounded.
  const verifyOnFetch = useRef<boolean>(false);

  const { data, isLoading, isFetching, refetch } =
    useQuery<BIMConvertersResponse>({
      queryKey: ['bim-converters'],
      queryFn: () => fetchBIMConverters({ verify: verifyOnFetch.current }),
      staleTime: 30_000,
    });

  // Compare each installed converter's package SHA-256 against the latest on
  // GitHub. Backend caches 6 h. When ``is_outdated`` is true for an
  // installed converter, we surface an "Update Available" badge with a
  // direct download link — users can drop the new exe into the same
  // location and re-run the smoke test. Network failures degrade
  // gracefully: ``data`` is null and the badge stays hidden.
  const { data: versionCheck } = useQuery<ConverterVersionCheck | null>({
    queryKey: ['bim-converters-version-check'],
    queryFn: () => fetchConverterVersionCheck(),
    staleTime: 30 * 60 * 1000, // 30 min — server caches 6 h
    refetchOnWindowFocus: false,
  });

  const versionByExt: Record<string, ConverterVersionCheck['converters'][0] | undefined> = {};
  for (const v of versionCheck?.converters ?? []) {
    versionByExt[v.id] = v;
  }

  const installMutation = useMutation({
    mutationFn: (vars: { converterId: string; force?: boolean }) =>
      installBIMConverter(vars.converterId, { force: vars.force }),
    onSuccess: (result, vars) => {
      const converterId = vars.converterId;
      const conv = data?.converters.find((c) => c.id === converterId);
      const sizeMb = conv?.size_mb ?? 0;
      const name = conv ? converterName(t, conv) : converterId.toUpperCase();

      if (result.installed) {
        addToast({
          type: 'success',
          title: t('bim.converter_install_success_title', {
            defaultValue: 'Converter installed',
          }),
          message:
            result.message ||
            t('bim.converter_install_success_msg', {
              defaultValue: 'Installed {{name}} ({{size}} MB)',
              name,
              size: sizeMb,
            }),
        });
      } else if (result.platform_unsupported) {
        addToast({
          type: 'warning',
          title: t('bim.converter_install_unsupported_title', {
            defaultValue: 'Auto-install not available',
          }),
          message: converterPlatformMessage(t, converterId),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('bim.converter_install_problem_title', {
            defaultValue: 'Converter install incomplete',
          }),
          message:
            result.message || `${name} install did not complete cleanly.`,
        });
      }
      // An install is an explicit user action, and "did it work?" is the
      // whole point of it - so the refetch below runs the smoke test even
      // though the passive listing does not (#416).
      verifyOnFetch.current = true;
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
      queryClient.invalidateQueries({ queryKey: ['bim-converters-version-check'] });
    },
    onError: (err, vars) => {
      const converterId = vars.converterId;
      const conv = data?.converters.find((c) => c.id === converterId);
      addToast({
        type: 'error',
        title: t('bim.converter_install_error_title', {
          defaultValue: 'Install failed',
        }),
        message:
          err instanceof Error
            ? err.message
            : t('bim.converter_install_error_msg', {
                defaultValue: 'Could not install {{name}}',
                name: conv ? converterName(t, conv) : converterId.toUpperCase(),
              }),
      });
    },
    onSettled: () => setInstallingId(null),
  });

  const verifyMutation = useMutation({
    mutationFn: (converterId: string) => verifyBIMConverter(converterId),
    onSuccess: (result, converterId) => {
      const conv = data?.converters.find((c) => c.id === converterId);
      const name = conv ? converterName(t, conv) : converterId.toUpperCase();
      if (result.health === 'ok') {
        addToast({
          type: 'success',
          title: t('bim.converter_verify_ok_title', {
            defaultValue: 'Converter is working',
          }),
          message: t('bim.converter_verify_ok_msg', {
            defaultValue: '{{name}} loaded successfully and is ready to use.',
            name,
          }),
        });
      } else {
        addToast(
          {
            type: 'warning',
            title: t('bim.converter_verify_failed_title', {
              defaultValue: 'Converter still broken',
            }),
            message: result.health_message || `${name} smoke test failed.`,
          },
          { duration: 20_000 },
        );
      }
      // The user chose to check this row. Keep the list verified from here
      // on, or the invalidation below would refetch the passive listing and
      // drop the verdict straight back to "Installed" (#416).
      verifyOnFetch.current = true;
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
    },
    onError: (err, converterId) => {
      // Backend < v2.6.23 didn't have the per-converter verify endpoint —
      // surface a clear "upgrade your backend" message instead of a bare
      // "Not Found" so the user knows what to do.
      const isMissingEndpoint =
        err instanceof Error
          && (err.message.includes('Not Found')
              || err.message.includes('404'));
      if (isMissingEndpoint) {
        addToast(
          {
            type: 'warning',
            title: t('bim.converter_verify_old_backend_title', {
              defaultValue: 'Backend version too old for Re-check',
            }),
            message: t('bim.converter_verify_old_backend_msg', {
              defaultValue:
                'Re-check requires backend v2.6.23 or newer. Update with: pip install --upgrade openconstructionerp',
            }),
          },
          { duration: 20_000 },
        );
        return;
      }
      addToast({
        type: 'error',
        title: t('bim.converter_verify_error_title', {
          defaultValue: 'Re-check failed',
        }),
        message:
          err instanceof Error
            ? err.message
            : `Could not run smoke test for ${converterId.toUpperCase()}.`,
      });
    },
    onSettled: () => setVerifyingId(null),
  });

  // Stable signature for the *current* set of upstream converter builds.
  // Built from the latest-SHA of every converter flagged outdated, sorted
  // so order is irrelevant. When DDC ships a new release this string
  // changes — that is what lets a dismissal expire for genuinely new
  // updates while still honouring an "X" press for the update the user
  // already saw and chose to ignore for now.
  const currentVersionSig = (versionCheck?.converters ?? [])
    .filter((v) => v.is_outdated)
    .map((v) => `${v.id}:${v.latest_sha ?? ''}`)
    .sort()
    .join('|');

  // Reconcile a dismissal that was recorded before the version-check query
  // resolved (collapsed strip / mini-icon X, or X pressed in the brief
  // post-mount window). Without this, ``dismissedVersionSig`` stays '' while
  // ``currentVersionSig`` becomes a real SHA, the equality check below flips
  // false, and the dismissed panel re-surfaces for good. Backfilling the now
  // -known signature scopes the dismissal to exactly the update the user
  // acknowledged; a genuinely newer upstream build later yields a *different*
  // non-empty signature and still re-surfaces the notice as intended.
  useEffect(() => {
    if (!dismissed || currentVersionSig === '') return;
    const wasUnscoped =
      dismissedBeforeSigKnown.current || dismissedVersionSig === '';
    if (wasUnscoped && dismissedVersionSig !== currentVersionSig) {
      dismissedBeforeSigKnown.current = false;
      setDismissedVersionSig(currentVersionSig);
      try {
        localStorage.setItem(
          'oe_bim_converter_panel_dismissed_sig',
          currentVersionSig,
        );
      } catch {
        /* storage unavailable */
      }
    }
  }, [dismissed, dismissedVersionSig, currentVersionSig]);

  // The "X" must always close the panel. The previous build let a
  // *blocking* signal (a missing/broken converter) override a dismissal so
  // the panel re-appeared on the very next render. That is the reported
  // "the close button does not dismiss the panel" bug. Closing is now an
  // explicit, honoured user choice: once the user presses X the panel
  // stays hidden.
  //
  // The one case where a dismissed panel is allowed to re-surface is a
  // genuinely *newer* upstream converter build, so the user still learns
  // about future updates instead of an X click silencing the panel
  // forever. We detect that purely from the version signature: the panel
  // re-surfaces only when a *concretely different, fully-resolved*
  // signature appears (``currentVersionSig`` non-empty AND different from
  // the one captured at dismissal time).
  //
  // Root cause of the original "X reappears forever" variant: the
  // ``['bim-converters-version-check']`` query has a 30 min staleTime and
  // is briefly ``undefined`` on every fresh mount/navigation, and the
  // collapsed-strip / mini-icon render paths expose the X before that
  // query has resolved. ``setDismissedPersist`` therefore persisted an
  // *empty* ``currentVersionSig``; once the version-check resolved with a
  // real SHA the recomputed ``currentVersionSig`` became non-empty, so
  // ``dismissedVersionSig('') === currentVersionSig('rvt:..')`` was false on
  // every subsequent render and the dismissal silently expired. An empty
  // ``currentVersionSig`` means "version-check not yet settled", i.e.
  // "no new information", so it must NOT re-surface a dismissed panel.
  const versionSigResolved = currentVersionSig !== '';
  const newerVersionSinceDismissal =
    Boolean(versionCheck?.any_outdated) &&
    versionSigResolved &&
    dismissedVersionSig !== currentVersionSig;

  if (dismissible && dismissed && !newerVersionSinceDismissal) return null;
  if (isLoading || !data) return null;

  // Pull the converters we care about, preserving the canonical order.
  const relevant: BIMConverterInfo[] = PANEL_CONVERTER_IDS.map((id) =>
    data.converters.find((c) => c.id === id),
  ).filter((c): c is BIMConverterInfo => Boolean(c));
  if (relevant.length === 0) return null;

  const computedHealth = (c: BIMConverterInfo): BIMConverterHealth => {
    if (c.health) return c.health;
    return c.installed ? 'unknown' : 'not_installed';
  };

  const healthyCount = relevant.filter(
    (c) => computedHealth(c) === 'ok',
  ).length;
  const failedCount = relevant.filter(
    (c) => computedHealth(c) === 'failed',
  ).length;
  const anyOutdated = Boolean(versionCheck?.any_outdated);
  // "All healthy" must mean both "smoke test passed" AND "on the latest
  // upstream SHA" — otherwise the green panel pill conflicts with the
  // amber per-row pills we render for outdated rows. Per spec: only show
  // green for converters that are updated to the latest version.
  const allHealthy = healthyCount === relevant.length && !anyOutdated;
  const anyFailed = failedCount > 0;

  // How much of what we are showing is a listing rather than a verdict.
  // An installed converter reports `unknown` when the response carried no
  // smoke-test result, which is the normal state now that the automatic
  // fetch does not verify (#416). The panel has to say so: with verify off,
  // `healthyCount` is 0 on a perfectly working machine, and the pill and
  // subtitle written for the verified case would read "0/4 up to date" and
  // "Without these, drag-and-drop will fail" beside four installed
  // converters.
  const installedCount = relevant.filter((c) => c.installed).length;
  const uncheckedCount = relevant.filter(
    (c) => c.installed && computedHealth(c) === 'unknown',
  ).length;
  const nothingChecked = installedCount > 0 && uncheckedCount === installedCount;
  // Everything is present and nobody has looked. This is what decides the
  // WORDING, and it deliberately ignores `anyOutdated`: an update being
  // available says nothing about whether a converter is on disk, so the
  // install prompt must not fire here either way.
  const uncheckedAllInstalled = nothingChecked && installedCount === relevant.length;
  // ...and with no update waiting either, the panel has nothing at all to
  // tell the user, which is what the collapsed badge means. `!anyOutdated`
  // mirrors `allHealthy` on purpose: an available update has always been
  // allowed to pull the panel back open, and #416 must not change that.
  // Deliberately NOT folded into `allHealthy`: green keeps meaning "we
  // started it and it answered", never "we did not ask".
  const uncheckedOk = uncheckedAllInstalled && !anyOutdated;

  const handleInstall = (converter: BIMConverterInfo): void => {
    setInstallingId(converter.id);
    installMutation.mutate({ converterId: converter.id });
  };

  /** Same as handleInstall but with ``force=true`` so the backend
   *  re-downloads even when a binary is already on disk. Wired to the
   *  per-row "Update" button surfaced when the version-check banner
   *  reports an outdated SHA. */
  const handleUpdate = (converter: BIMConverterInfo): void => {
    setInstallingId(converter.id);
    installMutation.mutate({ converterId: converter.id, force: true });
  };

  const handleVerify = (converter: BIMConverterInfo): void => {
    setVerifyingId(converter.id);
    verifyMutation.mutate(converter.id);
  };

  // The panel's own check button. This is the explicit user action #416
  // gates the smoke test on: everything up to here is a disk listing.
  const handleRefresh = (): void => {
    verifyOnFetch.current = true;
    refetch();
  };

  // ── Mini mode (everything is fine) ─────────────────────────────────────
  // When all converters are working AND on the latest upstream SHA, the
  // panel collapses to a single icon-only pill so the BIM page doesn't
  // waste real estate on a "0 problems found" banner. Click to expand the
  // full collapsed strip — and from there, "Show details" goes back to
  // the full panel. Per the founder (2026-05-07): when every converter is
  // already on the latest version this panel has nothing to say, so it should
  // shrink to a small badge somewhere on the page.
  //
  // `uncheckedOk` joins `allHealthy` here because of #416: with the smoke
  // test no longer running on arrival, a machine where all four converters
  // are installed and fine now reports 0 healthy, and gating the badge on
  // `allHealthy` alone would replace it with a full amber install panel on
  // three pages. The badge keeps the neutral slate of an unchecked row and
  // counts what we actually know - how many are installed.
  if (collapsed && (allHealthy || uncheckedOk) && !anyFailed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsedPersist(false)}
        title={
          allHealthy
            ? t('bim.converters_mini_tooltip', {
                defaultValue:
                  'BIM converters: {{count}}/{{total}} working and on the latest version. Click to view details.',
                count: healthyCount,
                total: relevant.length,
              })
            : t('bim.converters_mini_tooltip_unchecked', {
                defaultValue:
                  'BIM converters: {{count}}/{{total}} installed, not checked yet. Click to view details and run the check.',
                count: installedCount,
                total: relevant.length,
              })
        }
        aria-label={t('bim.converters_mini_aria', {
          defaultValue: 'BIM converter status',
        })}
        data-testid="bim-converters-mini-icon"
        className={clsx(
          'inline-flex items-center gap-1 px-2 py-1 rounded-full border text-[10px] font-medium',
          allHealthy
            ? 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition-colors'
            : 'bg-slate-50 dark:bg-slate-900/40 border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors',
          className,
        )}
      >
        {allHealthy ? <CheckCircle2 size={12} /> : <Check size={12} />}
        <span className="font-mono tabular-nums">
          {allHealthy ? healthyCount : installedCount}/{relevant.length}
        </span>
      </button>
    );
  }

  // ── Compact mode (collapsed) ───────────────────────────────────────────
  // Renders a single-line strip with a per-format pill for each converter
  // so the user keeps the at-a-glance status without the install nag
  // taking 30% of the viewport. Reachable in two ways:
  //   1. allHealthy → user clicked "Collapse" once.
  //   2. !allHealthy + defaultCollapsed (page already has a ready model)
  //      → first paint hides the body so the 3D scene is not pushed below
  //      the fold (audit P2-1).
  if (collapsed) {
    const stripTone = anyFailed
      ? 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-800'
      : allHealthy
        ? 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800'
        : uncheckedOk
          ? 'bg-slate-50 dark:bg-slate-900/40 border-slate-200 dark:border-slate-700'
          : 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800';
    const stripIcon = anyFailed ? (
      <ShieldAlert size={14} className="text-rose-600 dark:text-rose-400" />
    ) : allHealthy ? (
      <CheckCircle2 size={14} className="text-emerald-600 dark:text-emerald-400" />
    ) : uncheckedOk ? (
      <Check size={14} className="text-slate-500 dark:text-slate-400" />
    ) : (
      <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400" />
    );
    return (
      <div
        className={clsx('rounded-xl border px-3 py-2', stripTone, className)}
        role="status"
      >
        <div className="flex items-center gap-2 text-[12px] flex-wrap">
          {stripIcon}
          <span className="font-semibold text-content-primary">
            {t('bim.converter_panel_title', { defaultValue: 'BIM converters' })}
          </span>
          <div className="flex items-center gap-1">
            {relevant.map((conv) => (
              <CollapsedConverterPill
                key={conv.id}
                conv={conv}
                health={computedHealth(conv)}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={() => setCollapsedPersist(false)}
            className="ms-auto text-[11px] underline-offset-2 hover:underline text-content-secondary"
          >
            {t('bim.converters_show_details', { defaultValue: 'Show details' })}
          </button>
          {dismissible && (
            <button
              type="button"
              onClick={() =>
                setDismissedPersist(
                  true,
                  currentVersionSig,
                  versionSigResolved,
                )
              }
              className="p-1 rounded-md text-content-tertiary hover:bg-black/5 dark:hover:bg-white/10"
              title={t('bim.converters_dismiss', { defaultValue: 'Dismiss' })}
              aria-label={t('bim.converters_dismiss', {
                defaultValue: 'Dismiss',
              })}
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Tone selection: red if anything is broken, amber if missing,
  //    green if all healthy, default amber otherwise. ─────────────────────
  //    Slate sits between green and amber for "installed, nobody looked":
  //    amber is the install nag, and showing it to a user with nothing to
  //    install is a false alarm (#416).
  const toneClass = anyFailed
    ? 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-800'
    : allHealthy
      ? 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800'
      : uncheckedOk
        ? 'bg-slate-50 dark:bg-slate-900/40 border-slate-200 dark:border-slate-700'
        : 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800';

  const headerIcon = anyFailed ? (
    <ShieldAlert size={16} className="text-rose-600 dark:text-rose-400" />
  ) : allHealthy ? (
    <CheckCircle2 size={16} className="text-emerald-600 dark:text-emerald-400" />
  ) : uncheckedOk ? (
    <Check size={16} className="text-slate-500 dark:text-slate-400" />
  ) : (
    <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400" />
  );

  const headerTextTone = anyFailed
    ? 'text-rose-900 dark:text-rose-200'
    : allHealthy
      ? 'text-emerald-900 dark:text-emerald-200'
      : uncheckedOk
        ? 'text-slate-700 dark:text-slate-200'
        : 'text-amber-900 dark:text-amber-200';

  return (
    <div className={clsx('rounded-xl border p-3', toneClass, className)} role="status">
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">{headerIcon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className={clsx('text-xs font-semibold', headerTextTone)}>
              {t('bim.converter_panel_title', {
                defaultValue: 'BIM converters',
              })}
            </p>
            <span
              className={clsx(
                'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold border tabular-nums',
                anyFailed
                  ? 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800'
                  : allHealthy
                    ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800'
                    : nothingChecked
                      ? 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700'
                      : 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
              )}
            >
              {anyFailed
                ? t('bim.converter_panel_count_failed', {
                    defaultValue:
                      '{{failed}} broken · {{ok}}/{{total}} working',
                    failed: failedCount,
                    ok: healthyCount,
                    total: relevant.length,
                  })
                : /* Nobody has run the smoke test, so "working" is not a
                     number we have. Count what the listing does know. */
                  nothingChecked
                  ? t('bim.converter_panel_count_unchecked', {
                      defaultValue:
                        '{{installed}}/{{total}} installed · not checked',
                      installed: installedCount,
                      total: relevant.length,
                    })
                  : anyOutdated
                    ? t('bim.converter_panel_count_outdated', {
                        defaultValue:
                          '{{ok}}/{{total}} working · update available',
                        ok: healthyCount,
                        total: relevant.length,
                      })
                    : t('bim.converter_panel_count', {
                        defaultValue: '{{ok}}/{{total}} up to date',
                        ok: healthyCount,
                        total: relevant.length,
                      })}
            </span>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isFetching}
              className={clsx(
                'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium border transition-colors',
                'border-transparent hover:bg-black/5 dark:hover:bg-white/10',
                headerTextTone,
                isFetching && 'opacity-60 cursor-wait',
              )}
              title={
                nothingChecked
                  ? t('bim.converters_check_now_title', {
                      defaultValue:
                        'Start every installed converter once and report whether it runs',
                    })
                  : t('bim.converters_refresh_title', {
                      defaultValue: 'Re-scan disk + re-run smoke tests',
                    })
              }
              data-testid="bim-converters-check"
            >
              <RefreshCw
                size={11}
                className={isFetching ? 'animate-spin' : undefined}
              />
              {/* The control that used to just reload a list the page had
                  already smoke-tested is now the way the smoke test gets
                  run at all, so it says so while nothing has been checked
                  (#416). */}
              {nothingChecked
                ? t('bim.converters_check_now', { defaultValue: 'Check now' })
                : t('bim.converters_refresh', { defaultValue: 'Refresh' })}
            </button>
            {allHealthy && (
              <button
                type="button"
                onClick={() => setCollapsedPersist(true)}
                className="ms-auto text-[10px] underline-offset-2 hover:underline text-emerald-700 dark:text-emerald-300"
              >
                {t('bim.converters_collapse', { defaultValue: 'Collapse' })}
              </button>
            )}
            {dismissible && (
              <button
                type="button"
                onClick={() =>
                setDismissedPersist(
                  true,
                  currentVersionSig,
                  versionSigResolved,
                )
              }
                className={clsx(
                  'p-1 rounded-md transition-colors',
                  !allHealthy && 'ms-auto',
                  anyFailed
                    ? 'text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/40'
                    : allHealthy
                      ? 'text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40'
                      : 'text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40',
                )}
                title={t('bim.converters_dismiss', {
                  defaultValue: 'Dismiss',
                })}
                aria-label={t('bim.converters_dismiss', {
                  defaultValue: 'Dismiss',
                })}
              >
                <X size={12} />
              </button>
            )}
          </div>
          <p className={clsx('text-[11px] mt-0.5 opacity-90', headerTextTone)}>
            {anyFailed
              ? t('bim.converter_panel_subtitle_failed', {
                  defaultValue:
                    'One or more converters cannot load. Conversion will fail until you reinstall.',
                })
              : healthyCount === relevant.length && anyOutdated
                ? t('bim.converter_panel_subtitle_outdated', {
                    defaultValue:
                      'All converters are working, but a newer version is available - we recommend updating.',
                  })
                : allHealthy
                  ? t('bim.converter_panel_subtitle_ok', {
                      defaultValue:
                        'Converters are ready: RVT and IFC models open in BIM Hub, DWG drawings in DWG Takeoff.',
                    })
                  : /* Everything is installed and unchecked: there is
                       nothing to install, so the install nag below would be
                       a false alarm. Say what is true and offer the check
                       (#416). `uncheckedAllInstalled`, not `uncheckedOk`:
                       an available update leaves the header reading "4/4
                       installed" and must not put "One-time install from
                       GitHub" underneath it. The update itself is not lost -
                       the tone stays amber and the update banner renders
                       right below this line. */
                    uncheckedAllInstalled
                    ? t('bim.converter_panel_subtitle_unchecked', {
                        defaultValue:
                          'All converters are installed. Nothing has been started yet to confirm they run - use Check now.',
                      })
                    : t('bim.converter_panel_subtitle_missing', {
                        defaultValue:
                          'Without these, drag-and-drop of native CAD/BIM files will fail. One-time install from GitHub.',
                      })}
          </p>
          {versionCheck?.any_outdated && !updateBannerDismissed && (
            <div
              className="mt-2 flex items-start gap-2 rounded-md border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 px-2.5 py-1.5 text-[11px] text-amber-900 dark:text-amber-200"
              data-testid="bim-converters-update-banner"
            >
              <AlertTriangle
                size={13}
                className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-300"
              />
              <div className="flex-1 leading-snug">
                <span className="font-semibold">
                  {t('bim.converter_panel_update_available', {
                    defaultValue: 'A new version is available',
                  })}
                </span>
                {' - '}
                {t('bim.converter_panel_update_recommend', {
                  defaultValue:
                    'we recommend updating using the Update button next to each row.',
                })}
              </div>
              <button
                type="button"
                onClick={() => setUpdateBannerDismissedSession(true)}
                title={t('bim.converter_panel_update_dismiss', {
                  defaultValue: 'Hide until next session',
                })}
                aria-label={t('bim.converter_panel_update_dismiss', {
                  defaultValue: 'Hide until next session',
                })}
                className="shrink-0 -m-1 p-1 rounded-md text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40"
              >
                <X size={12} />
              </button>
            </div>
          )}
          <ul className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
            {relevant.map((conv) => (
              <ConverterRow
                key={conv.id}
                conv={conv}
                health={computedHealth(conv)}
                installing={
                  installingId === conv.id && installMutation.isPending
                }
                verifying={
                  verifyingId === conv.id && verifyMutation.isPending
                }
                onInstall={() => handleInstall(conv)}
                onVerify={() => handleVerify(conv)}
                versionEntry={versionByExt[conv.id]}
                onUpdate={() => handleUpdate(conv)}
              />
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

interface CollapsedConverterPillProps {
  conv: BIMConverterInfo;
  health: BIMConverterHealth;
}

function CollapsedConverterPill({
  conv,
  health,
}: CollapsedConverterPillProps): JSX.Element {
  const { t } = useTranslation();
  const hasFallback = CONVERTERS_WITH_FALLBACK.has(conv.id);
  let tone: string;
  let label: string;
  if (health === 'ok') {
    tone = 'bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800';
    label = conv.id.toUpperCase();
  } else if (health === 'failed') {
    tone = 'bg-rose-100 text-rose-700 border-rose-300 dark:bg-rose-900/30 dark:text-rose-300 dark:border-rose-800';
    label = conv.id.toUpperCase();
  } else if (health === 'unknown') {
    tone = 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700';
    label = conv.id.toUpperCase();
  } else if (hasFallback) {
    tone = 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-900';
    label = `${conv.id.toUpperCase()} (fallback)`;
  } else {
    tone = 'bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800';
    label = conv.id.toUpperCase();
  }
  const titleSuffix =
    health === 'ok'
      ? t('bim.converter_pill_ok', { defaultValue: 'Installed and verified' })
      : health === 'failed'
        ? t('bim.converter_pill_failed', { defaultValue: 'Installed but smoke test failed' })
        : health === 'unknown'
          ? t('bim.converter_pill_unknown', { defaultValue: 'Installed (verify pending)' })
          : hasFallback
            ? t('bim.converter_pill_fallback', { defaultValue: 'Works without DDC (fallback parser)' })
            : t('bim.converter_pill_missing', { defaultValue: 'Not installed' });
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border tabular-nums',
        tone,
      )}
      title={`${converterName(t, conv)} - ${titleSuffix}`}
    >
      {label}
    </span>
  );
}

interface ConverterRowProps {
  conv: BIMConverterInfo;
  health: BIMConverterHealth;
  installing: boolean;
  verifying: boolean;
  onInstall: () => void;
  onVerify: () => void;
  versionEntry?: ConverterVersionCheck['converters'][0];
  /** Optional one-click update handler. When provided AND the converter
   *  is flagged outdated, the row renders an **Update** action that
   *  reuses the install flow (same GitHub source the version check
   *  compared against) so the user does not have to manually download
   *  and overwrite files. Falls back to the GitHub-blob link when no
   *  handler is provided. */
  onUpdate?: () => void;
}

function ConverterRow({
  conv,
  health,
  installing,
  verifying,
  onInstall,
  onVerify,
  versionEntry,
  onUpdate,
}: ConverterRowProps): JSX.Element {
  const { t } = useTranslation();
  const actions: BIMConverterAction[] = conv.suggested_actions ?? [];
  const updateAvailable = !!versionEntry?.is_outdated;

  // Choose icon + tone purely from health so the same "broken" tone shows
  // for both "not installed" and "installed but broken" — but the action
  // set differs.
  let icon: JSX.Element;
  let labelTone: string;
  let pillTone: string;
  let pillText: string;
  switch (health) {
    case 'ok':
      // Green is reserved for "working AND on the latest upstream SHA". When
      // the version-check flags this row as outdated, downgrade to amber so
      // green only ever means "fully up to date". Per the founder
      // (2026-05-07): show green only for converters that are updated to the
      // latest version.
      if (updateAvailable) {
        icon = (
          <AlertTriangle
            size={13}
            className="text-amber-600 dark:text-amber-400"
          />
        );
        labelTone = 'text-amber-900 dark:text-amber-200';
        pillTone =
          'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800';
        pillText = t('bim.converter_row_ok_outdated', {
          defaultValue: 'Working · update available',
        });
      } else {
        icon = (
          <Check
            size={13}
            className="text-emerald-600 dark:text-emerald-400"
          />
        );
        labelTone = 'text-emerald-900 dark:text-emerald-200';
        pillTone =
          'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
        pillText = t('bim.converter_row_ok', { defaultValue: 'Working' });
      }
      break;
    case 'failed':
      icon = (
        <XCircle size={13} className="text-rose-600 dark:text-rose-400" />
      );
      labelTone = 'text-rose-900 dark:text-rose-200';
      pillTone =
        'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800';
      pillText = t('bim.converter_row_failed', {
        defaultValue: 'Broken',
      });
      break;
    case 'unknown':
      icon = (
        <Check
          size={13}
          className="text-slate-500 dark:text-slate-400"
        />
      );
      labelTone = 'text-slate-700 dark:text-slate-200';
      pillTone =
        'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700';
      pillText = t('bim.converter_row_unknown', {
        defaultValue: 'Installed',
      });
      break;
    case 'not_installed':
    default:
      if (CONVERTERS_WITH_FALLBACK.has(conv.id)) {
        // Soft-green: the format works without the binary because a
        // built-in fallback parser exists. Action button still reads
        // "Install" because installing the binary upgrades fidelity
        // (real meshes vs placeholder boxes), but the status pill no
        // longer scares users into thinking the format is broken.
        icon = (
          <CheckCircle2
            size={13}
            className="text-emerald-600 dark:text-emerald-400"
          />
        );
        labelTone = 'text-emerald-900 dark:text-emerald-200';
        pillTone =
          'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
        pillText = t('bim.converter_row_fallback', {
          defaultValue: 'Works without DDC (fallback)',
        });
      } else {
        icon = (
          <Download
            size={13}
            className="text-amber-600 dark:text-amber-400"
          />
        );
        labelTone = 'text-amber-900 dark:text-amber-200';
        pillTone =
          'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800';
        pillText = t('bim.converter_row_missing', {
          defaultValue: 'Install required',
        });
      }
      break;
  }

  // Background tint per state — subtle, gives each row a "card" feel
  // without competing with the surrounding panel chrome. Per the founder
  // (2026-05-07): make it visually cleaner and easier to read.
  const rowBg =
    health === 'failed'
      ? 'bg-rose-50/60 dark:bg-rose-950/30 border-rose-200/70 dark:border-rose-900/60'
      : health === 'ok'
        ? updateAvailable
          ? 'bg-amber-50/60 dark:bg-amber-950/30 border-amber-200/70 dark:border-amber-900/60'
          : 'bg-emerald-50/60 dark:bg-emerald-950/30 border-emerald-200/70 dark:border-emerald-900/60'
        : health === 'unknown'
          ? 'bg-slate-50/60 dark:bg-slate-900/40 border-slate-200/70 dark:border-slate-700/60'
          : 'bg-amber-50/60 dark:bg-amber-950/30 border-amber-200/70 dark:border-amber-900/60';

  return (
    <li className={clsx('text-[11px] rounded-lg border px-2.5 py-2', rowBg)}>
      <div className="flex items-center gap-2.5">
        <span className="shrink-0">{icon}</span>
        <span className={clsx('font-semibold tracking-tight', labelTone)}>
          {converterName(t, conv)}
        </span>
        <span
          className={clsx(
            'tabular-nums text-[10px] opacity-70',
            health === 'ok' && !updateAvailable
              ? 'text-emerald-700 dark:text-emerald-300'
              : health === 'failed'
                ? 'text-rose-700 dark:text-rose-300'
                : 'text-amber-700 dark:text-amber-300',
          )}
        >
          {t('bim.converter_panel_size', {
            defaultValue: '{{size}} MB',
            size: conv.size_mb,
          })}
        </span>
        {conv.format_range && (
          <span className="hidden xl:inline truncate max-w-[200px] text-[10px] text-content-quaternary opacity-80">
            {conv.format_range}
          </span>
        )}
        {/* Show the actual installed binary SHA (first 7 chars). When an
            update is available we tack on " → def5678" so users see what
            they have *and* what they would get without opening a tooltip.
            Falls back to nothing when the version-check hasn't resolved
            yet (offline / GitHub rate-limited / pre-Linux). */}
        {conv.installed && (
          <span
            className="hidden lg:inline text-[10px] text-content-quaternary dark:text-zinc-400 font-mono"
            title={
              versionEntry?.installed_sha
                ? t('bim.converter_sha_tooltip', {
                    defaultValue:
                      'Installed package SHA-256: {{sha}}. Compared with the package this version installs from the DDC converter release.',
                    sha: versionEntry.installed_sha,
                  })
                : undefined
            }
          >
            {converterVersionLabel(versionEntry?.installed_version, conv.version)}
            {updateAvailable && versionEntry?.latest_version && (
              <span className="text-sky-600 dark:text-sky-400">
                {' '}→ v{versionEntry.latest_version}
              </span>
            )}
          </span>
        )}
        {updateAvailable && onUpdate && (
          <button
            type="button"
            onClick={onUpdate}
            disabled={installing}
            title={t('bim.converter_update_tooltip', {
              defaultValue:
                'A newer build of this converter is available. Click to download and replace the installed copy.',
            })}
            className="ms-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border border-sky-300 dark:border-sky-700 bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300 hover:bg-sky-200 dark:hover:bg-sky-900/50 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {installing ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Download size={11} />
            )}
            {installing
              ? t('bim.converter_updating', { defaultValue: 'Updating…' })
              : t('bim.converter_update_now', { defaultValue: 'Update' })}
          </button>
        )}
        {updateAvailable && !onUpdate && versionEntry?.html_url && (
          <a
            href={versionEntry.html_url}
            target="_blank"
            rel="noopener noreferrer"
            title={t('bim.converter_update_link_tooltip', {
              defaultValue:
                'A newer build of this converter is available on GitHub. Open the file there to download manually.',
            })}
            className="ms-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border border-sky-300 dark:border-sky-700 bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300 hover:bg-sky-200 dark:hover:bg-sky-900/50 transition-colors"
          >
            <Download size={11} />
            {t('bim.converter_update_available', {
              defaultValue: 'Update available',
            })}
          </a>
        )}
        <span
          className={clsx(
            'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border',
            !updateAvailable && 'ms-auto',
            pillTone,
          )}
        >
          {pillText}
        </span>
        {/* Always-on Re-check button for installed-but-unknown rows so the
         *  user can run the smoke test on demand even when auto-verify
         *  hasn't completed (or hasn't been triggered). Failed rows get
         *  this button below alongside Reinstall; not_installed rows
         *  don't need it because there's nothing to test. */}
        {health === 'unknown' && (
          <button
            type="button"
            onClick={onVerify}
            disabled={verifying}
            className="ms-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {verifying ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <RefreshCw size={11} />
            )}
            {t('bim.converter_row_recheck', { defaultValue: 'Re-check' })}
          </button>
        )}
      </div>

      {/* Reason + action row when something needs attention */}
      {(health === 'failed' || health === 'not_installed') && (
        <div
          className={clsx(
            'ms-5 mt-1 rounded-md border px-2 py-1.5 space-y-1.5',
            health === 'failed'
              ? 'border-rose-200 dark:border-rose-800 bg-rose-100/40 dark:bg-rose-900/20'
              : CONVERTERS_WITH_FALLBACK.has(conv.id)
                ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-100/40 dark:bg-emerald-900/20'
                : 'border-amber-200 dark:border-amber-800 bg-amber-100/40 dark:bg-amber-900/20',
          )}
        >
          {health === 'not_installed' && CONVERTERS_WITH_FALLBACK.has(conv.id) && (
            <p className="text-[11px] text-emerald-800 dark:text-emerald-200">
              {t('bim.converter_row_fallback_msg', {
                defaultValue:
                  'IFC files are parsed by a built-in fallback. Install the DDC binary to upgrade placeholder boxes to real meshes.',
              })}
            </p>
          )}
          {conv.health_message && (
            <p
              className={clsx(
                'text-[11px]',
                health === 'failed'
                  ? 'text-rose-800 dark:text-rose-200'
                  : 'text-amber-800 dark:text-amber-200',
              )}
            >
              {conv.health_message}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {(actions.length === 0
              ? health === 'not_installed'
                ? (['install_converter'] as BIMConverterAction[])
                : (['reinstall_converter'] as BIMConverterAction[])
              : actions
            ).map((action) => (
              <ActionButton
                key={action}
                action={action}
                installing={installing}
                onInstall={onInstall}
              />
            ))}
            {health === 'failed' && (
              <button
                type="button"
                onClick={onVerify}
                disabled={verifying}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                {verifying ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <RefreshCw size={11} />
                )}
                {t('bim.converter_row_recheck', {
                  defaultValue: 'Re-check',
                })}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Live download/update progress, rendered for ANY in-flight install,
          including the "Update" action on a healthy (health === 'ok') row,
          which previously fell outside the failed/not_installed block and so
          showed only a bare "Updating..." spinner with no progress bar. The
          shared ConverterInstallProgressBar polls /install-progress/ itself
          and shows an indeterminate bar immediately (before the first poll
          lands), then a determinate file-count bar plus stage/file/MB
          microcopy once the backend reports totals. */}
      {installing && (
        <div className="ms-5 mt-1.5">
          <ConverterInstallProgressBar
            converterId={conv.id}
            installing={installing}
            sizeMb={conv.size_mb}
          />
        </div>
      )}
    </li>
  );
}

interface ActionButtonProps {
  action: BIMConverterAction;
  installing: boolean;
  onInstall: () => void;
}

/** Maps a stable backend `suggested_actions` id to a concrete UI control.
 *  External-link actions open in a new tab; install actions trigger the
 *  shared install mutation in the parent. */
function ActionButton({
  action,
  installing,
  onInstall,
}: ActionButtonProps): JSX.Element | null {
  const { t } = useTranslation();

  switch (action) {
    case 'install_converter':
      return (
        <button
          type="button"
          onClick={onInstall}
          disabled={installing}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-amber-600 hover:bg-amber-700 disabled:opacity-60 disabled:cursor-not-allowed text-white transition-colors"
        >
          {installing ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              {t('bim.converter_panel_installing', {
                defaultValue: 'Downloading…',
              })}
            </>
          ) : (
            <>
              <Download size={11} />
              {t('bim.converter_panel_install_btn', {
                defaultValue: 'Install',
              })}
            </>
          )}
        </button>
      );
    case 'reinstall_converter':
      return (
        <button
          type="button"
          onClick={onInstall}
          disabled={installing}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-rose-600 hover:bg-rose-700 disabled:opacity-60 disabled:cursor-not-allowed text-white transition-colors"
        >
          {installing ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              {t('bim.converter_panel_installing', {
                defaultValue: 'Downloading…',
              })}
            </>
          ) : (
            <>
              <Download size={11} />
              {t('bim.converter_panel_reinstall_btn', {
                defaultValue: 'Reinstall',
              })}
            </>
          )}
        </button>
      );
    case 'install_vc_redist':
      return (
        <a
          href={VC_REDIST_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
        >
          <ExternalLink size={11} />
          {t('bim.converter_panel_vcredist_btn', {
            defaultValue: 'Install VC++ Redist',
          })}
        </a>
      );
    case 'manual_install_from_github':
      return (
        <a
          href={DDC_REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
        >
          <ExternalLink size={11} />
          {t('bim.converter_panel_manual_install_btn', {
            defaultValue: 'Manual install on GitHub',
          })}
        </a>
      );
    case 'unblock_files':
      return (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"
          title={t('bim.converter_panel_unblock_help', {
            defaultValue:
              'Right-click each .exe and .dll → Properties → tick "Unblock" → OK',
          })}
        >
          {t('bim.converter_panel_unblock_label', {
            defaultValue: 'Unblock files (Mark of the Web)',
          })}
        </span>
      );
    case 'check_permissions':
      return (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"
          title={t('bim.converter_panel_perms_help', {
            defaultValue:
              'Run the converter once as Administrator, or move the install dir somewhere your user can write to.',
          })}
        >
          {t('bim.converter_panel_perms_label', {
            defaultValue: 'Run as Administrator',
          })}
        </span>
      );
    default:
      return null;
  }
}

export default BIMConverterStatusBanner;
