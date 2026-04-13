import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Sparkles,
  FileSearch,
  Box,
  ArrowRight,
  Upload,
  Ruler,
  Layers3,
  MessageSquareText,
  ExternalLink,
  CheckCircle2,
  Download,
  HardDrive,
  FileInput,
  Loader2,
  Trash2,
  XCircle,
  FileText,
  Clock,
  Star,
} from 'lucide-react';
import { apiGet, apiPost } from '@/shared/lib/api';
import { Breadcrumb } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

// ── Types ────────────────────────────────────────────────────────────────

interface TakeoffDocument {
  id?: string;
  name?: string;
  filename?: string;
  created_at?: string;
  type?: string;
  file_type?: string;
}

interface MethodCard {
  titleKey: string;
  descriptionKey: string;
  icon: React.ElementType;
  gradient: string;
  iconBg: string;
  route: string;
  badgeKey?: string;
  badgeColor?: string;
  available: boolean;
}

interface ConverterInfo {
  id: string;
  name: string;
  description: string;
  engine: string;
  extensions: string[];
  exe: string;
  version: string;
  size_mb: number;
  installed: boolean;
  path: string | null;
}

interface ConvertersResponse {
  converters: ConverterInfo[];
  installed_count: number;
  total_count: number;
}

interface InstallResult {
  converter_id: string;
  installed: boolean;
  path: string;
  already_installed?: boolean;
  size_bytes?: number;
  message: string;
}

// ── localStorage helpers (legacy — kept for migration, prefer API status) ──

const INSTALLED_CONVERTERS_KEY = 'oe_installed_converters';

function getInstalledConverters(): string[] {
  try {
    const raw = localStorage.getItem(INSTALLED_CONVERTERS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addInstalledConverter(id: string): void {
  try {
    const current = getInstalledConverters();
    if (!current.includes(id)) {
      localStorage.setItem(INSTALLED_CONVERTERS_KEY, JSON.stringify([...current, id]));
    }
  } catch {
    /* localStorage unavailable */
  }
}

function removeInstalledConverter(id: string): void {
  try {
    const current = getInstalledConverters();
    localStorage.setItem(
      INSTALLED_CONVERTERS_KEY,
      JSON.stringify(current.filter((c) => c !== id)),
    );
  } catch {
    /* localStorage unavailable */
  }
}

// ── Static data ──────────────────────────────────────────────────────────

const GITHUB_RELEASES_URL =
  'https://github.com/datadrivenconstruction/ddc-community-toolkit/releases';

const methods: MethodCard[] = [
  {
    titleKey: 'quantities.method_ai_title',
    descriptionKey: 'quantities.method_ai_desc',
    icon: Sparkles,
    gradient:
      'from-violet-500/10 to-blue-500/10 hover:from-violet-500/15 hover:to-blue-500/15',
    iconBg: 'bg-gradient-to-br from-violet-500 to-blue-500',
    route: '/ai-estimate',
    badgeKey: 'quantities.badge_ai',
    badgeColor: 'bg-gradient-to-r from-violet-500 to-blue-500 text-white',
    available: true,
  },
  {
    titleKey: 'quantities.method_pdf_title',
    descriptionKey: 'quantities.method_pdf_desc',
    icon: FileSearch,
    gradient:
      'from-blue-500/10 to-cyan-500/10 hover:from-blue-500/15 hover:to-cyan-500/15',
    iconBg: 'bg-gradient-to-br from-blue-500 to-cyan-500',
    route: '/takeoff',
    available: true,
  },
  {
    titleKey: 'quantities.method_cad_title',
    descriptionKey: 'quantities.method_cad_desc',
    icon: Box,
    gradient:
      'from-emerald-500/10 to-teal-500/10 hover:from-emerald-500/15 hover:to-teal-500/15',
    iconBg: 'bg-gradient-to-br from-emerald-500 to-teal-500',
    route: '/data-explorer',
    badgeKey: 'quantities.badge_cad',
    badgeColor:
      'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    available: true,
  },
];

const steps = [
  {
    num: '1',
    titleKey: 'quantities.step1_title',
    descKey: 'quantities.step1_desc',
    icon: Upload,
  },
  {
    num: '2',
    titleKey: 'quantities.step2_title',
    descKey: 'quantities.step2_desc',
    icon: Ruler,
  },
  {
    num: '3',
    titleKey: 'quantities.step3_title',
    descKey: 'quantities.step3_desc',
    icon: Layers3,
  },
];

// Color map for converter cards
const CONVERTER_COLORS: Record<string, { bg: string; border: string; icon: string }> = {
  dwg: {
    bg: 'from-red-500/8 to-orange-500/8',
    border: 'border-red-200 dark:border-red-900/30',
    icon: 'bg-gradient-to-br from-red-500 to-orange-500',
  },
  rvt: {
    bg: 'from-blue-500/8 to-indigo-500/8',
    border: 'border-blue-200 dark:border-blue-900/30',
    icon: 'bg-gradient-to-br from-blue-500 to-indigo-500',
  },
  ifc: {
    bg: 'from-emerald-500/8 to-green-500/8',
    border: 'border-emerald-200 dark:border-emerald-900/30',
    icon: 'bg-gradient-to-br from-emerald-500 to-green-500',
  },
  dgn: {
    bg: 'from-purple-500/8 to-violet-500/8',
    border: 'border-purple-200 dark:border-purple-900/30',
    icon: 'bg-gradient-to-br from-purple-500 to-violet-500',
  },
};

// ── Converter card component ────────────────────────────────────────────

function ConverterCard({
  converter,
  installing,
  isInstalled: _isInstalled,
  onInstall,
  onUninstall,
  disabled,
}: {
  converter: ConverterInfo;
  installing: boolean;
  isInstalled: boolean;
  onInstall: () => void;
  onUninstall: () => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const colors = CONVERTER_COLORS[converter.id] ?? CONVERTER_COLORS['dwg'] ?? { bg: 'from-gray-500/8 to-gray-500/8', border: 'border-gray-200', icon: 'bg-gray-500' };
  const installed = converter.installed;

  return (
    <div
      className={clsx(
        'group relative flex flex-col rounded-xl border p-5 transition-all duration-200',
        installed
          ? 'border-emerald-300 dark:border-emerald-800/50 bg-gradient-to-br from-emerald-500/5 to-teal-500/5'
          : clsx(
              'bg-gradient-to-br',
              colors.bg,
              colors.border,
              'ring-2 ring-oe-blue/30 animate-pulse-border',
            ),
        disabled && !installing ? 'opacity-40 pointer-events-none' : '',
      )}
    >
      {/* Recommended badge for uninstalled converters */}
      {!installed && !installing && (
        <div className="absolute -top-2.5 left-4 z-10">
          <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-amber-400 to-orange-500 px-2.5 py-0.5 text-2xs font-bold text-white shadow-sm">
            <Star size={10} />
            {t('quantities.recommended', { defaultValue: 'Recommended' })}
          </span>
        </div>
      )}

      {/* Status badge */}
      <div className="absolute top-3 right-3">
        {installing ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-2xs font-semibold text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
            <Loader2 size={10} className="animate-spin" />
            {t('quantities.converter_installing', { defaultValue: 'Installing...' })}
          </span>
        ) : installed ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-2xs font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
            <CheckCircle2 size={10} />
            {t('quantities.converter_installed', { defaultValue: 'Installed' })}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-2xs font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
            <Download size={10} />
            {t('quantities.converter_available', { defaultValue: 'Available' })}
          </span>
        )}
      </div>

      {/* Icon */}
      <div
        className={clsx(
          'flex h-10 w-10 items-center justify-center rounded-lg text-white',
          installed ? 'bg-gradient-to-br from-emerald-500 to-teal-500' : colors.icon,
        )}
      >
        <FileInput size={20} strokeWidth={1.75} />
      </div>

      {/* Name + engine */}
      <h3 className="mt-3 text-sm font-semibold text-content-primary">{converter.name}</h3>
      <p className="mt-0.5 text-2xs text-content-quaternary">{converter.engine}</p>

      {/* Description */}
      <p className="mt-2 text-xs text-content-tertiary leading-relaxed line-clamp-2">
        {converter.description}
      </p>

      {/* Extensions */}
      <div className="mt-3 flex flex-wrap gap-1">
        {converter.extensions.map((ext) => (
          <span
            key={ext}
            className="inline-flex rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-mono text-content-secondary"
          >
            {ext}
          </span>
        ))}
      </div>

      {/* Footer: size + actions */}
      <div className="mt-3 flex items-center justify-between pt-2 border-t border-border-light">
        <span className="text-2xs text-content-quaternary">
          v{converter.version} &middot;{' '}
          {converter.size_mb >= 1024
            ? `${(converter.size_mb / 1024).toFixed(1)} GB`
            : `${converter.size_mb} MB`}
        </span>

        <div className="flex items-center gap-1.5">
          {installed ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onUninstall();
              }}
              disabled={installing || disabled}
              className="inline-flex items-center gap-1 rounded bg-red-50 dark:bg-red-900/20 px-2 py-1 text-2xs font-medium text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
            >
              <Trash2 size={10} />
              {t('quantities.uninstall', { defaultValue: 'Uninstall' })}
            </button>
          ) : (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onInstall();
              }}
              disabled={installing || disabled}
              className="inline-flex items-center gap-1 rounded bg-oe-blue/10 px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/20 transition-colors"
            >
              {installing ? (
                <Loader2 size={10} className="animate-spin" />
              ) : (
                <Download size={10} />
              )}
              {t('quantities.install_with_size', {
                defaultValue: 'Install ({{size}} MB)',
                size: converter.size_mb,
              })}
            </button>
          )}
          <span className="inline-flex items-center gap-1 rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
            {t('quantities.module_label', { defaultValue: 'Module' })}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Install progress panel ──────────────────────────────────────────────

function InstallProgressPanel({
  installing,
  converterName,
  elapsed,
  result,
  error,
  onDismiss,
}: {
  installing: boolean;
  converterName: string;
  elapsed: number;
  result: InstallResult | null;
  error: string | null;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();

  // Phase-based progress simulation
  const phase = elapsed < 5 ? 0 : elapsed < 15 ? 1 : elapsed < 30 ? 2 : 3;
  const phaseLabels = [
    t('quantities.phase_downloading', { defaultValue: 'Downloading from GitHub...' }),
    t('quantities.phase_extracting', { defaultValue: 'Extracting converter files...' }),
    t('quantities.phase_verifying', { defaultValue: 'Verifying executable...' }),
    t('quantities.phase_finalizing', { defaultValue: 'Finalizing...' }),
  ];
  const progressPct = error
    ? 100
    : result
      ? 100
      : Math.min(
          95,
          phase === 0
            ? elapsed * 8
            : phase === 1
              ? 40 + (elapsed - 5) * 3
              : phase === 2
                ? 70 + (elapsed - 15) * 1.5
                : 92 + (elapsed - 30) * 0.1,
        );

  return (
    <div className="rounded-2xl border border-border-light bg-surface-elevated overflow-hidden shadow-sm">
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-center gap-3 mb-4">
          {error ? (
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 dark:bg-red-900/20">
              <XCircle size={22} className="text-red-500" />
            </div>
          ) : result ? (
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-success-bg">
              <CheckCircle2 size={22} className="text-semantic-success" />
            </div>
          ) : (
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
              <HardDrive size={20} className="text-oe-blue" />
              <div className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-oe-blue animate-ping" />
              <div className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-oe-blue" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {error
                  ? t('quantities.install_failed', {
                      defaultValue: 'Installation failed',
                    })
                  : result
                    ? t('quantities.install_success', {
                        defaultValue: 'Converter installed successfully',
                      })
                    : t('quantities.installing_converter', {
                        defaultValue: `Installing ${converterName}...`,
                        name: converterName,
                      })}
              </h3>
              {installing && (
                <span className="text-xs text-oe-blue font-mono tabular-nums">
                  {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
                </span>
              )}
            </div>
            <p className="text-xs text-content-tertiary mt-0.5">
              {error
                ? error
                : result
                  ? t('quantities.install_ready', {
                      defaultValue: 'Converter is ready to use for CAD/BIM file processing.',
                    })
                  : t('quantities.install_downloading', {
                      defaultValue:
                        'Installing converter module. This is a one-time setup.',
                    })}
            </p>
          </div>
          {(result || error) && (
            <button
              onClick={onDismiss}
              className="text-content-quaternary hover:text-content-secondary transition-colors"
            >
              <XCircle size={18} />
            </button>
          )}
        </div>

        {/* Progress bar */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-content-secondary">
              {error ? 'Failed' : result ? 'Complete' : phaseLabels[phase]}
            </span>
            <span
              className={clsx(
                'text-xs font-semibold tabular-nums',
                error ? 'text-red-500' : 'text-oe-blue',
              )}
            >
              {Math.round(progressPct)}%
            </span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className={clsx(
                'h-full rounded-full transition-all duration-1000 ease-out',
                error
                  ? 'bg-red-500'
                  : result
                    ? 'bg-semantic-success'
                    : 'bg-gradient-to-r from-oe-blue via-blue-400 to-oe-blue bg-[length:200%_100%] animate-shimmer',
              )}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Phase steps */}
        {installing && (
          <div className="flex items-center gap-1 text-2xs">
            {['Download', 'Extract', 'Verify', 'Done'].map((label, i) => (
              <div key={label} className="flex items-center gap-1">
                <div
                  className={clsx(
                    'h-1.5 w-1.5 rounded-full',
                    i < phase
                      ? 'bg-semantic-success'
                      : i === phase
                        ? 'bg-oe-blue animate-pulse'
                        : 'bg-surface-tertiary',
                  )}
                />
                <span
                  className={
                    i <= phase
                      ? 'text-content-secondary font-medium'
                      : 'text-content-quaternary'
                  }
                >
                  {label}
                </span>
                {i < 3 && <span className="text-content-quaternary mx-0.5">&middot;</span>}
              </div>
            ))}
          </div>
        )}

        {/* Success details */}
        {result && (
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-semantic-success-bg/50 px-3 py-2 text-center">
              <div className="text-sm font-bold text-[#15803d]">{converterName}</div>
              <div className="text-2xs text-[#15803d]/70">
                {t('quantities.result_installed', { defaultValue: 'installed' })}
              </div>
            </div>
            <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
              <div className="text-sm font-bold text-content-primary">
                {t('quantities.result_ready', { defaultValue: 'Ready' })}
              </div>
              <div className="text-2xs text-content-tertiary">
                {t('quantities.result_use_cad', { defaultValue: 'Use in AI Estimate → CAD/BIM' })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Info strip */}
      <div className="px-5 py-3 bg-surface-secondary/50 border-t border-border-light">
        <div className="flex items-center gap-4 text-2xs text-content-tertiary">
          <span className="flex items-center gap-1">
            <HardDrive size={10} /> {t('quantities.module_label', { defaultValue: 'Module' })}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> {t('quantities.open_source', { defaultValue: 'Open Source' })}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" /> {t('quantities.free_label', { defaultValue: 'Free' })}
          </span>
          <span className="ml-auto font-medium text-content-secondary">
            {result
              ? t('quantities.info_ready', { defaultValue: 'Ready to use' })
              : t('quantities.info_onetime', { defaultValue: 'One-time install' })}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Installed converters table ──────────────────────────────────────────

function InstalledConvertersTable({
  converters,
  onUninstall,
  uninstalling,
}: {
  converters: ConverterInfo[];
  onUninstall: (id: string) => void;
  uninstalling: string | null;
}) {
  const { t } = useTranslation();
  const installed = converters.filter((c) => c.installed);

  if (installed.length === 0) return null;

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('quantities.installed_converters', { defaultValue: 'Installed Converters' })}
          </h3>
          <p className="text-2xs text-content-quaternary mt-0.5">
            {t('quantities.installed_count', {
              defaultValue: '{{count}} converter(s) detected',
              count: installed.length,
            })}
          </p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th className="pb-2 pr-4 font-medium">
                {t('quantities.table_converter', { defaultValue: 'Converter' })}
              </th>
              <th className="pb-2 pr-4 font-medium">
                {t('quantities.table_formats', { defaultValue: 'Formats' })}
              </th>
              <th className="pb-2 pr-4 font-medium">
                {t('quantities.table_status', { defaultValue: 'Status' })}
              </th>
              <th className="pb-2 pr-4 font-medium">
                {t('quantities.table_version', { defaultValue: 'Version' })}
              </th>
              <th className="pb-2 font-medium w-20"></th>
            </tr>
          </thead>
          <tbody>
            {installed.map((c) => (
              <tr key={c.id} className="border-b border-border-light last:border-0">
                <td className="py-2.5 pr-4 font-medium text-content-primary">{c.name}</td>
                <td className="py-2.5 pr-4">
                  <div className="flex flex-wrap gap-1">
                    {c.extensions.map((ext) => (
                      <span
                        key={ext}
                        className="inline-flex rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-mono text-content-secondary"
                      >
                        {ext}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="py-2.5 pr-4">
                  <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 size={12} />
                    <span className="text-xs">
                      {t('quantities.status_loaded', { defaultValue: 'Loaded' })}
                    </span>
                  </span>
                </td>
                <td className="py-2.5 pr-4 text-xs text-content-quaternary font-mono">
                  v{c.version}
                </td>
                <td className="py-2.5">
                  <button
                    onClick={() => onUninstall(c.id)}
                    disabled={uninstalling === c.id}
                    className="inline-flex items-center gap-1 rounded px-2 py-1 text-2xs text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                  >
                    {uninstalling === c.id ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      <Trash2 size={10} />
                    )}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────

export function QuantitiesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Converter data from API
  const { data: convertersData } = useQuery<ConvertersResponse>({
    queryKey: ['takeoff', 'converters'],
    queryFn: () => apiGet<ConvertersResponse>('/v1/takeoff/converters/'),
    staleTime: 30_000,
  });

  // Recent documents from API
  const { data: documents } = useQuery({
    queryKey: ['takeoff', 'documents'],
    queryFn: () => apiGet<TakeoffDocument[]>('/v1/takeoff/documents/'),
  });

  const converters = convertersData?.converters ?? [];
  const installedCount = convertersData?.installed_count ?? 0;
  const totalCount = convertersData?.total_count ?? 4;

  // Install state
  const [installing, setInstalling] = useState<string | null>(null);
  const [localInstalled, setLocalInstalled] = useState<Set<string>>(
    () => new Set(getInstalledConverters()),
  );
  const [installResult, setInstallResult] = useState<InstallResult | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [uninstalling, setUninstalling] = useState<string | null>(null);

  // Elapsed timer during install
  useEffect(() => {
    if (!installing) {
      setElapsed(0);
      return;
    }
    const interval = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(interval);
  }, [installing]);

  // Install handler
  const handleInstall = useCallback(
    async (converter: ConverterInfo) => {
      setInstalling(converter.id);
      setInstallResult(null);
      setInstallError(null);

      try {
        const data = await apiPost<InstallResult>(
          `/v1/takeoff/converters/${converter.id}/install`,
        );

        setLocalInstalled((prev) => new Set(prev).add(converter.id));
        addInstalledConverter(converter.id);
        setInstallResult(data);

        addToast({
          type: 'success',
          title: `${converter.name} installed`,
          message: data.message,
        });

        // Refresh converter status from API
        queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
      } catch (err: unknown) {
        const detail =
          err instanceof Error ? err.message : 'Failed to install converter';
        setInstallError(detail);
        addToast({
          type: 'error',
          title: `Failed to install ${converter.name}`,
          message: detail,
        });
      } finally {
        setInstalling(null);
      }
    },
    [addToast, queryClient],
  );

  // Uninstall handler
  const handleUninstall = useCallback(
    async (converterId: string) => {
      const converter = converters.find((c) => c.id === converterId);
      const name = converter?.name ?? converterId;
      setUninstalling(converterId);

      try {
        await apiPost(`/v1/takeoff/converters/${converterId}/uninstall/`);

        setLocalInstalled((prev) => {
          const next = new Set(prev);
          next.delete(converterId);
          return next;
        });
        removeInstalledConverter(converterId);

        addToast({
          type: 'success',
          title: `${name} uninstalled`,
          message: 'Converter has been removed.',
        });

        queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
      } catch (err: unknown) {
        const detail =
          err instanceof Error ? err.message : 'Failed to uninstall converter';
        addToast({
          type: 'error',
          title: `Failed to uninstall ${name}`,
          message: detail,
        });
      } finally {
        setUninstalling(null);
      }
    },
    [addToast, converters, queryClient],
  );

  const dismissProgress = useCallback(() => {
    setInstallResult(null);
    setInstallError(null);
  }, []);

  // Get the name of the currently installing converter
  const installingConverterName =
    converters.find((c) => c.id === installing)?.name ?? installing ?? '';

  return (
    <div className="mx-auto max-w-content space-y-8 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.quantities', 'Quantity Takeoff') }]} className="mb-4" />
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-content-primary">
          {t('quantities.title', { defaultValue: 'Quantity Takeoff' })}
        </h1>
        <p className="mt-1 text-sm text-content-tertiary">
          {t('quantities.subtitle', {
            defaultValue:
              'Collect project quantities — from AI text input, PDF drawings, or CAD/BIM models',
          })}
        </p>
      </div>

      {/* Method cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {methods.map((method) => {
          const Icon = method.icon;
          return (
            <button
              key={method.route}
              onClick={() => method.available && navigate(method.route)}
              disabled={!method.available}
              className={clsx(
                'group relative flex flex-col rounded-xl border border-border-light p-6 text-left transition-all duration-200',
                method.available
                  ? `bg-gradient-to-br ${method.gradient} cursor-pointer hover:shadow-md hover:border-oe-blue/30`
                  : 'opacity-60 cursor-not-allowed bg-surface-secondary',
              )}
            >
              {method.badgeKey && (
                <span
                  className={clsx(
                    'absolute top-3 right-3 inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-semibold',
                    method.badgeColor,
                  )}
                >
                  {t(method.badgeKey)}
                </span>
              )}

              <div
                className={clsx(
                  'flex h-12 w-12 items-center justify-center rounded-xl text-white',
                  method.iconBg,
                )}
              >
                <Icon size={24} strokeWidth={1.75} />
              </div>

              <h3 className="mt-4 text-lg font-semibold text-content-primary">
                {t(method.titleKey)}
              </h3>
              <p className="mt-1 text-sm text-content-tertiary leading-relaxed">
                {t(method.descriptionKey)}
              </p>

              {method.available && (
                <div className="mt-4 flex items-center gap-1 text-sm font-medium text-oe-blue opacity-0 transition-opacity group-hover:opacity-100">
                  {t('quantities.open', { defaultValue: 'Open' })}
                  <ArrowRight size={14} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* How it works */}
      <div className="rounded-xl border border-border-light bg-surface-primary p-6">
        <h2 className="text-lg font-semibold text-content-primary">
          {t('quantities.how_it_works', { defaultValue: 'How it works' })}
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {steps.map((step) => (
            <div key={step.num} className="flex gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-sm font-bold text-oe-blue">
                {step.num}
              </div>
              <div>
                <p className="text-sm font-medium text-content-primary">
                  {t(step.titleKey)}
                </p>
                <p className="mt-0.5 text-xs text-content-tertiary">{t(step.descKey)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── CAD/BIM Converter Modules ──────────────────────────────── */}
      <div className="space-y-4">
        {/* Header card */}
        <div className="rounded-xl border border-border-light bg-surface-primary p-5">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white">
              <HardDrive size={24} strokeWidth={1.75} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-content-primary">
                  {t('quantities.converters_title', {
                    defaultValue: 'CAD/BIM Converter Modules',
                  })}
                </h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-2xs font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                  {installedCount}/{totalCount} {t('quantities.installed_label', { defaultValue: 'installed' })}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-content-quaternary">
                {t('quantities.converters_author', {
                  defaultValue: 'DDC Community · Open Source · Free',
                })}
              </p>
            </div>
          </div>
          <p className="mt-3 text-sm text-content-secondary leading-relaxed">
            {t('quantities.converters_desc', {
              defaultValue:
                'Install converter modules to extract elements, quantities, and geometry from CAD/BIM files. Each module handles a specific file format and transforms it into structured data for AI-powered cost estimation.',
            })}
          </p>
          <button
            onClick={() => navigate('/data-explorer')}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-oe-blue/10 px-3 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/20 transition-colors"
          >
            <Box size={14} />
            {t('quantities.go_to_cad_takeoff', { defaultValue: 'Go to CAD/BIM Takeoff' })}
            <ArrowRight size={12} />
          </button>
        </div>

        {/* Converter module cards — 2-column grid */}
        <div className="grid gap-3 sm:grid-cols-2">
          {converters.map((converter) => (
            <ConverterCard
              key={converter.id}
              converter={converter}
              installing={installing === converter.id}
              isInstalled={localInstalled.has(converter.id)}
              onInstall={() => handleInstall(converter)}
              onUninstall={() => handleUninstall(converter.id)}
              disabled={installing !== null && installing !== converter.id}
            />
          ))}
        </div>

        {/* Fallback when API hasn't loaded yet — show skeleton cards */}
        {converters.length === 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {['dwg', 'rvt', 'ifc', 'dgn'].map((id) => {
              const colors = CONVERTER_COLORS[id] ?? CONVERTER_COLORS['dwg'] ?? { bg: 'from-gray-500/8 to-gray-500/8', border: 'border-gray-200', icon: 'bg-gray-500' };
              return (
                <div
                  key={id}
                  className={clsx(
                    'rounded-xl border p-5 animate-pulse',
                    colors.border,
                    'bg-gradient-to-br',
                    colors.bg,
                  )}
                >
                  <div className="h-10 w-10 rounded-lg bg-surface-tertiary" />
                  <div className="mt-3 h-4 w-32 rounded bg-surface-tertiary" />
                  <div className="mt-2 h-3 w-full rounded bg-surface-tertiary" />
                  <div className="mt-1 h-3 w-3/4 rounded bg-surface-tertiary" />
                </div>
              );
            })}
          </div>
        )}

        {/* Install progress panel */}
        {(installing || installResult || installError) && (
          <InstallProgressPanel
            installing={installing !== null}
            converterName={
              installResult
                ? converters.find((c) => c.id === installResult.converter_id)?.name ??
                  installResult.converter_id
                : installingConverterName
            }
            elapsed={elapsed}
            result={installResult}
            error={installError}
            onDismiss={dismissProgress}
          />
        )}

        {/* Installed converters table */}
        <InstalledConvertersTable
          converters={converters}
          onUninstall={handleUninstall}
          uninstalling={uninstalling}
        />

        {/* Module info footer */}
        <div className="flex flex-wrap items-center gap-3 text-xs text-content-quaternary px-1">
          <span className="flex items-center gap-1.5">
            <CheckCircle2 size={11} />
            {t('quantities.modules_managed', {
              defaultValue: 'Modules are managed automatically by the platform',
            })}
          </span>
          <a
            href={GITHUB_RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue transition-colors"
          >
            <ExternalLink size={11} />
            {t('quantities.source_code', {
              defaultValue: 'Source code',
            })}
          </a>
        </div>
      </div>

      {/* Quick manual entry */}
      <div className="rounded-xl border border-border-light bg-surface-primary p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('quantities.manual_title', { defaultValue: 'Quick Manual Entry' })}
            </h2>
            <p className="mt-0.5 text-sm text-content-tertiary">
              {t('quantities.manual_desc', {
                defaultValue: 'Need to add quantities directly? Go to the BOQ Editor.',
              })}
            </p>
          </div>
          <button
            onClick={() => navigate('/boq')}
            className="flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-oe-blue-dark"
          >
            <MessageSquareText size={16} />
            {t('quantities.open_boq', { defaultValue: 'Open BOQ Editor' })}
          </button>
        </div>
      </div>

      {/* Recent Documents */}
      <div className="rounded-xl border border-border-light bg-surface-primary p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
              <FileText size={20} className="text-blue-500" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('quantities.recent_documents_title', { defaultValue: 'Recent Documents' })}
              </h2>
              <p className="text-xs text-content-quaternary">
                {t('quantities.recent_documents_count', {
                  defaultValue: '{{count}} document(s) uploaded',
                  count: documents?.length ?? 0,
                })}
              </p>
            </div>
          </div>
        </div>

        {documents && documents.length > 0 ? (
          <div className="space-y-2">
            {documents.slice(0, 10).map((doc, idx) => (
              <div
                key={doc.id ?? idx}
                className="flex items-center justify-between rounded-lg border border-border-light px-4 py-3 hover:bg-surface-secondary transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <FileText size={16} className="shrink-0 text-content-quaternary" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-content-primary truncate">
                      {doc.name ?? doc.filename ?? t('quantities.unnamed_document', { defaultValue: 'Unnamed document' })}
                    </p>
                    <div className="flex items-center gap-2 text-2xs text-content-quaternary">
                      {doc.created_at && (
                        <span className="flex items-center gap-1">
                          <Clock size={10} />
                          {new Date(doc.created_at).toLocaleDateString()}
                        </span>
                      )}
                      {(doc.type ?? doc.file_type) && (
                        <span className="rounded bg-surface-tertiary px-1.5 py-0.5 font-mono uppercase">
                          {doc.type ?? doc.file_type}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <FileText size={32} className="text-content-quaternary mb-3" />
            <p className="text-sm text-content-tertiary">
              {t('quantities.no_documents', { defaultValue: 'No documents uploaded yet' })}
            </p>
            <button
              onClick={() => navigate('/takeoff')}
              className="mt-3 flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-oe-blue-dark"
            >
              <Upload size={16} />
              {t('quantities.upload_document', { defaultValue: 'Upload Document' })}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
