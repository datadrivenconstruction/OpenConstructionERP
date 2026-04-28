/**
 * BIMConverterStatusBanner — always-visible health panel for the four DDC
 * converters needed by the BIM Hub drag-and-drop (.rvt / .ifc / .dwg / .dgn).
 *
 * v2.6.23 architecture: the banner is the single source of truth for
 * converter state on /bim. It does three things the previous version did
 * not:
 *  1. Includes IFC (the "Revit and IFC don't load" complaint was rooted
 *     in IFC never being surfaced — the install button was unreachable).
 *  2. Stays visible even when everything is healthy, so the user can
 *     verify rather than guess.
 *  3. Polls the backend with `verify=true`, which runs an 8 s smoke test
 *     per installed converter. A binary that exists on disk but cannot
 *     load (Qt6 DLL missing, Mark-of-the-Web, VCRedist absent) shows up
 *     here as ⚠ Failed, with the specific reason and one-click fix
 *     buttons mapped from the backend's `suggested_actions`.
 *
 * Cache: shares the `['bim-converters']` React-Query key with the upload
 * preflight in BIMPage so an install / verify here invalidates both.
 */

import { useState } from 'react';
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
  installBIMConverter,
  verifyBIMConverter,
  type BIMConverterAction,
  type BIMConverterHealth,
  type BIMConverterInfo,
  type BIMConvertersResponse,
} from './api';
import { useToastStore } from '@/stores/useToastStore';

/** Ids of converters surfaced on the BIM page. IFC was previously missing
 *  here — that's why "Revit and IFC don't load" was reported as a bug. */
const PANEL_CONVERTER_IDS = ['rvt', 'ifc', 'dwg', 'dgn'] as const;

/** GitHub root for the manual-install fallback links. */
const DDC_REPO_URL =
  'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN';

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
}

export function BIMConverterStatusBanner({
  className,
  dismissible = false,
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
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('oe_bim_converter_panel_collapsed') === '1';
    } catch {
      return false;
    }
  });

  const setDismissedPersist = (val: boolean): void => {
    setDismissed(val);
    try {
      localStorage.setItem(
        'oe_bim_converter_panel_dismissed',
        val ? '1' : '0',
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

  // Fetch with `verify=true` so each installed converter gets a smoke test.
  // The backend caches results 5 min, so the polling is cheap.
  const { data, isLoading, isFetching, refetch } =
    useQuery<BIMConvertersResponse>({
      queryKey: ['bim-converters'],
      queryFn: () => fetchBIMConverters({ verify: true }),
      staleTime: 30_000,
    });

  const installMutation = useMutation({
    mutationFn: (converterId: string) => installBIMConverter(converterId),
    onSuccess: (result, converterId) => {
      const conv = data?.converters.find((c) => c.id === converterId);
      const sizeMb = conv?.size_mb ?? 0;
      const name = conv?.name ?? converterId.toUpperCase();

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
      } else if (result.platform_unsupported && result.platform === 'linux') {
        const apt = result.apt_package
          ? `\n\nsudo apt install -y ${result.apt_package}`
          : '';
        addToast(
          {
            type: 'info',
            title: t('bim.converter_install_linux_title', {
              defaultValue: 'Linux auto-install unavailable',
            }),
            message:
              (result.message || `Run apt commands to install ${name}`) + apt,
          },
          { duration: 30_000 },
        );
      } else if (result.platform_unsupported) {
        addToast({
          type: 'warning',
          title: t('bim.converter_install_unsupported_title', {
            defaultValue: 'Auto-install not available',
          }),
          message:
            result.message || `${name} can't be auto-installed on this OS.`,
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
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
    },
    onError: (err, converterId) => {
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
                name: conv?.name ?? converterId.toUpperCase(),
              }),
      });
    },
    onSettled: () => setInstallingId(null),
  });

  const verifyMutation = useMutation({
    mutationFn: (converterId: string) => verifyBIMConverter(converterId),
    onSuccess: (result, converterId) => {
      const conv = data?.converters.find((c) => c.id === converterId);
      const name = conv?.name ?? converterId.toUpperCase();
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

  if (dismissible && dismissed) return null;
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
  const allHealthy = healthyCount === relevant.length;
  const anyFailed = failedCount > 0;

  const handleInstall = (converter: BIMConverterInfo): void => {
    setInstallingId(converter.id);
    installMutation.mutate(converter.id);
  };

  const handleVerify = (converter: BIMConverterInfo): void => {
    setVerifyingId(converter.id);
    verifyMutation.mutate(converter.id);
  };

  const handleRefresh = (): void => {
    refetch();
  };

  // ── Compact mode (all healthy + collapsed) ─────────────────────────────
  if (allHealthy && collapsed) {
    return (
      <div
        className={clsx(
          'rounded-xl border bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800 px-3 py-2',
          className,
        )}
        role="status"
      >
        <div className="flex items-center gap-2 text-[12px]">
          <CheckCircle2
            size={14}
            className="text-emerald-600 dark:text-emerald-400"
          />
          <span className="font-semibold text-emerald-900 dark:text-emerald-200">
            {t('bim.converters_all_ready', {
              defaultValue: 'All BIM converters verified',
            })}
          </span>
          <span className="text-emerald-700/80 dark:text-emerald-300/80 tabular-nums">
            ({healthyCount}/{relevant.length})
          </span>
          <button
            type="button"
            onClick={() => setCollapsedPersist(false)}
            className="ms-auto text-[11px] underline-offset-2 hover:underline text-emerald-700 dark:text-emerald-300"
          >
            {t('bim.converters_show_details', { defaultValue: 'Show details' })}
          </button>
          {dismissible && (
            <button
              type="button"
              onClick={() => setDismissedPersist(true)}
              className="p-1 rounded-md text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/40"
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
  const toneClass = anyFailed
    ? 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-800'
    : allHealthy
      ? 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800'
      : 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800';

  const headerIcon = anyFailed ? (
    <ShieldAlert size={16} className="text-rose-600 dark:text-rose-400" />
  ) : allHealthy ? (
    <CheckCircle2 size={16} className="text-emerald-600 dark:text-emerald-400" />
  ) : (
    <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400" />
  );

  const headerTextTone = anyFailed
    ? 'text-rose-900 dark:text-rose-200'
    : allHealthy
      ? 'text-emerald-900 dark:text-emerald-200'
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
                : t('bim.converter_panel_count', {
                    defaultValue: '{{ok}}/{{total}} verified',
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
              title={t('bim.converters_refresh_title', {
                defaultValue: 'Re-scan disk + re-run smoke tests',
              })}
            >
              <RefreshCw
                size={11}
                className={isFetching ? 'animate-spin' : undefined}
              />
              {t('bim.converters_refresh', { defaultValue: 'Refresh' })}
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
                onClick={() => setDismissedPersist(true)}
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
              : allHealthy
                ? t('bim.converter_panel_subtitle_ok', {
                    defaultValue:
                      'Drag-and-drop of .rvt / .ifc / .dwg / .dgn is ready.',
                  })
                : t('bim.converter_panel_subtitle_missing', {
                    defaultValue:
                      'Without these, drag-and-drop of native CAD/BIM files will fail. One-time install from GitHub.',
                  })}
          </p>
          <ul className="mt-2 space-y-1.5">
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
              />
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

interface ConverterRowProps {
  conv: BIMConverterInfo;
  health: BIMConverterHealth;
  installing: boolean;
  verifying: boolean;
  onInstall: () => void;
  onVerify: () => void;
}

function ConverterRow({
  conv,
  health,
  installing,
  verifying,
  onInstall,
  onVerify,
}: ConverterRowProps): JSX.Element {
  const { t } = useTranslation();
  const actions: BIMConverterAction[] = conv.suggested_actions ?? [];

  // Choose icon + tone purely from health so the same "broken" tone shows
  // for both "not installed" and "installed but broken" — but the action
  // set differs.
  let icon: JSX.Element;
  let labelTone: string;
  let pillTone: string;
  let pillText: string;
  switch (health) {
    case 'ok':
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
        defaultValue: 'Not installed',
      });
      break;
  }

  return (
    <li className="text-[11px]">
      <div className="flex items-center gap-2">
        <span className="shrink-0">{icon}</span>
        <span className={clsx('font-medium', labelTone)}>{conv.name}</span>
        <span
          className={clsx(
            'tabular-nums',
            health === 'ok'
              ? 'text-emerald-700/80 dark:text-emerald-300/80'
              : health === 'failed'
                ? 'text-rose-700/80 dark:text-rose-300/80'
                : 'text-amber-700/80 dark:text-amber-300/80',
          )}
        >
          {t('bim.converter_panel_size', {
            defaultValue: '{{size}} MB',
            size: conv.size_mb,
          })}
        </span>
        {health === 'ok' && conv.path && (
          <span
            className="hidden md:inline truncate max-w-[280px] text-[10px] text-emerald-700/70 dark:text-emerald-300/70 font-mono"
            title={conv.path}
          >
            {conv.path}
          </span>
        )}
        <span
          className={clsx(
            'ms-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border',
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
              : 'border-amber-200 dark:border-amber-800 bg-amber-100/40 dark:bg-amber-900/20',
          )}
        >
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
