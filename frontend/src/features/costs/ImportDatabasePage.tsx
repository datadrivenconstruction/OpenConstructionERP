import { useState, useCallback, useRef, useEffect, type DragEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Database,
  Download,
  Trash2,
  Star,
  Sparkles,
} from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, CountryFlag } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiGet, apiPost, apiDelete, triggerDownload } from '@/shared/lib/api';

// ── Types ────────────────────────────────────────────────────────────────────

interface ImportResult {
  imported: number;
  skipped: number;
  errors: Array<{
    row: number;
    error: string;
    data: Record<string, string>;
  }>;
  total_rows: number;
}

// ── Loaded databases localStorage helper ────────────────────────────────────

const LOADED_DBS_KEY = 'oe_loaded_databases';
const ACTIVE_DB_KEY = 'oe_active_database';

function getLoadedDatabases(): string[] {
  try {
    const raw = localStorage.getItem(LOADED_DBS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addLoadedDatabase(dbId: string): void {
  try {
    const current = getLoadedDatabases();
    if (!current.includes(dbId)) {
      localStorage.setItem(LOADED_DBS_KEY, JSON.stringify([...current, dbId]));
    }
  } catch {
    // Storage unavailable -- ignore.
  }
}

function removeLoadedDatabase(dbId: string): void {
  try {
    const current = getLoadedDatabases();
    localStorage.setItem(LOADED_DBS_KEY, JSON.stringify(current.filter((d) => d !== dbId)));
    // If removed the active one, clear it
    if (localStorage.getItem(ACTIVE_DB_KEY) === dbId) {
      const remaining = current.filter((d) => d !== dbId);
      localStorage.setItem(ACTIVE_DB_KEY, remaining[0] ?? '');
    }
  } catch {
    // Storage unavailable -- ignore.
  }
}

function clearLoadedDatabases(): void {
  try {
    localStorage.removeItem(LOADED_DBS_KEY);
    localStorage.removeItem(ACTIVE_DB_KEY);
  } catch {
    // Storage unavailable -- ignore.
  }
}

interface RegionStat {
  region: string;
  count: number;
}

function getActiveDatabase(): string | null {
  try {
    return localStorage.getItem(ACTIVE_DB_KEY);
  } catch {
    return null;
  }
}

function setActiveDatabase(dbId: string): void {
  try {
    localStorage.setItem(ACTIVE_DB_KEY, dbId);
  } catch {
    // Storage unavailable -- ignore.
  }
}

// ── API helper for file upload ───────────────────────────────────────────────

async function uploadCostFile(file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append('file', file);

  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/costs/import/file', {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Upload failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ImportResult>;
}

// ── File Preview Info ────────────────────────────────────────────────────────

interface FilePreview {
  name: string;
  size: string;
  type: 'excel' | 'csv';
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileType(name: string): 'excel' | 'csv' | null {
  const lower = name.toLowerCase();
  if (lower.endsWith('.xlsx') || lower.endsWith('.xls')) return 'excel';
  if (lower.endsWith('.csv')) return 'csv';
  return null;
}

// ── CWICR Regional Databases ─────────────────────────────────────────────────

interface CWICRDatabase {
  id: string;
  name: string;
  city: string;
  lang: string;
  currency: string;
  flagId: string;
  parquetName: string;
}

const CWICR_DATABASES: CWICRDatabase[] = [
  { id: 'USA_USD', name: 'United States', city: 'New York', lang: 'English', currency: 'USD', flagId: 'us', parquetName: 'USA_USD' },
  { id: 'UK_GBP', name: 'United Kingdom', city: 'London', lang: 'English', currency: 'GBP', flagId: 'gb', parquetName: 'UK_GBP' },
  { id: 'DE_BERLIN', name: 'Germany / DACH', city: 'Berlin', lang: 'Deutsch', currency: 'EUR', flagId: 'de', parquetName: 'DE_BERLIN' },
  { id: 'ENG_TORONTO', name: 'Canada / International', city: 'Toronto', lang: 'English', currency: 'CAD', flagId: 'ca', parquetName: 'ENG_TORONTO' },
  { id: 'FR_PARIS', name: 'France', city: 'Paris', lang: 'Francais', currency: 'EUR', flagId: 'fr', parquetName: 'FR_PARIS' },
  { id: 'SP_BARCELONA', name: 'Spain / Latin America', city: 'Barcelona', lang: 'Espanol', currency: 'EUR', flagId: 'es', parquetName: 'SP_BARCELONA' },
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', city: 'Sao Paulo', lang: 'Portugues', currency: 'BRL', flagId: 'br', parquetName: 'PT_SAOPAULO' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', city: 'St. Petersburg', lang: 'Russian', currency: 'RUB', flagId: 'ru', parquetName: 'RU_STPETERSBURG' },
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', city: 'Dubai', lang: 'Arabic', currency: 'AED', flagId: 'ae', parquetName: 'AR_DUBAI' },
  { id: 'ZH_SHANGHAI', name: 'China', city: 'Shanghai', lang: 'Chinese', currency: 'CNY', flagId: 'cn', parquetName: 'ZH_SHANGHAI' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in', parquetName: 'HI_MUMBAI' },
];

// Databases that may only be available via GitHub download (not in local DDC_Toolkit)
const GITHUB_ONLY_DBS = new Set(['UK_GBP', 'USA_USD']);

/** Mini flag component — uses bundled inline SVGs */
function MiniFlag({ code }: { code: string }) {
  return <CountryFlag code={code} size={32} className="shadow-xs border border-black/5" />;
}

function CWICRDatabaseGrid(_props: { onLoadDatabase: (file: File) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [loading, setLoading] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Set<string>>(() => new Set(getLoadedDatabases()));
  const [result, setResult] = useState<{
    id: string;
    imported: number;
    skipped: number;
    file: string;
  } | null>(null);
  const [lastLoadedDb, setLastLoadedDb] = useState<CWICRDatabase | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [activeDb, setActiveDb] = useState<string | null>(() => getActiveDatabase());
  const addToast = useToastStore((s) => s.addToast);

  // Sync loaded state with actual backend data
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats'),
    retry: false,
  });

  useEffect(() => {
    if (regionStats) {
      const actualRegions = new Set(regionStats.map((r) => r.region));
      setLoaded(actualRegions);
    }
  }, [regionStats]);

  // Timer for elapsed time display
  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(interval);
  }, [loading]);

  const handleSetActive = useCallback(
    (dbId: string) => {
      setActiveDatabase(dbId);
      setActiveDb(dbId);
      addToast({
        type: 'success',
        title: t('costs.active_db_changed', { defaultValue: 'Active database changed' }),
        message: `${CWICR_DATABASES.find((d) => d.id === dbId)?.name ?? dbId} ${t('costs.is_now_active', { defaultValue: 'is now the active database' })}`,
      });
    },
    [addToast, t],
  );

  const handleLoad = useCallback(
    async (db: CWICRDatabase) => {
      setLoading(db.id);
      setResult(null);
      setLastLoadedDb(db);

      void GITHUB_ONLY_DBS; // Referenced in JSX badge

      try {
        const data = await apiPost<Record<string, unknown>>(`/v1/costs/load-cwicr/${db.id}`);

        setLoaded((prev) => new Set(prev).add(db.id));
        addLoadedDatabase(db.id);

        // Auto-set as active if it is the first loaded database
        const allLoaded = getLoadedDatabases();
        if (allLoaded.length === 1 || !getActiveDatabase()) {
          setActiveDatabase(db.id);
          setActiveDb(db.id);
        }

        const status = data.status as string | undefined;
        const imported = (data.imported as number) ?? 0;
        const totalItems = (data.total_items as number) ?? imported;

        setResult({
          id: db.id,
          imported,
          skipped: (data.skipped as number) ?? 0,
          file: (data.source_file as string) ?? '',
        });

        if (status === 'already_loaded') {
          addToast({
            type: 'info',
            title: `${db.name} already loaded`,
            message: (data.message as string) ?? `${totalItems.toLocaleString()} items available`,
          });
        } else {
          addToast({
            type: 'success',
            title: t('costs.db_installed', { defaultValue: 'Database installed successfully' }),
            message: `${imported.toLocaleString()} cost items imported`,
          });
        }

        // Invalidate all cost queries so LoadedDatabasesSection and other consumers refresh
        queryClient.invalidateQueries({ queryKey: ['costs'] });

        // Auto-index vectors in background — don't await (it takes 30-60s and blocks UI)
        apiPost('/v1/costs/vector/index').catch((err) => {
          console.error('Vector indexing failed (non-critical):', err);
        });
      } catch (err: unknown) {
        const detail =
          err instanceof Error ? err.message : 'Failed to load database';
        addToast({
          type: 'error',
          title: `Failed to load ${db.name}`,
          message: detail,
        });
      } finally {
        setLoading(null);
      }
    },
    [addToast, t, queryClient],
  );

  return (
    <div>
      {/* Database grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {CWICR_DATABASES.map((db) => {
          const isLoading = loading === db.id;
          const isLoaded = loaded.has(db.id);
          const isActive = activeDb === db.id;
          const isGithub = GITHUB_ONLY_DBS.has(db.id);

          return (
            <div
              key={db.id}
              className={`
                relative flex flex-col rounded-xl
                border transition-all duration-normal ease-oe
                ${
                  isLoaded
                    ? isActive
                      ? 'border-oe-blue/40 bg-oe-blue-subtle/20'
                      : 'border-semantic-success/30 bg-semantic-success-bg/40'
                    : isLoading
                      ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
                      : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary'
                }
                ${loading !== null && !isLoading ? 'opacity-40 pointer-events-none' : ''}
              `}
            >
              <button
                onClick={() => handleLoad(db)}
                disabled={isLoading || loading !== null}
                className="flex items-center gap-3 px-3.5 py-3 text-left active:scale-[0.98] transition-transform"
              >
                <MiniFlag code={db.flagId} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">
                      {db.name}
                    </span>
                    {isLoaded && (
                      <CheckCircle2
                        size={14}
                        className="text-semantic-success shrink-0"
                      />
                    )}
                  </div>
                  <div className="text-2xs text-content-tertiary">
                    {db.city} &middot; {db.lang} &middot; {db.currency}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className="text-2xs text-content-quaternary">{t('costs.items_count', { defaultValue: '55,719 items' })}</span>
                    {isGithub && !isLoaded && (
                      <Badge variant="blue" size="sm" className="text-2xs px-1.5 py-0">
                        GitHub
                      </Badge>
                    )}
                    {!isGithub && !isLoaded && (
                      <Badge variant="neutral" size="sm" className="text-2xs px-1.5 py-0">
                        Local
                      </Badge>
                    )}
                  </div>
                </div>
                {isLoading && (
                  <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" />
                )}
              </button>

              {/* Action row for loaded databases */}
              {isLoaded && (
                <div className="flex items-center gap-1.5 px-3.5 pb-2.5 -mt-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSetActive(db.id);
                    }}
                    className={`
                      flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium transition-colors
                      ${
                        isActive
                          ? 'bg-oe-blue text-white'
                          : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                      }
                    `}
                  >
                    <Star size={10} className={isActive ? 'fill-current' : ''} />
                    {isActive ? t('costs.active', { defaultValue: 'Active' }) : t('costs.set_active', { defaultValue: 'Set as Active' })}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Import Progress Panel ─────────────────────────────────────── */}
      {(loading || result) && (() => {
        const loadingDb = loading ? CWICR_DATABASES.find((d) => d.id === loading) : lastLoadedDb;
        // Simulate phased progress: 0-15s = reading file, 15-30s = parsing, 30+ = writing
        const phase = elapsed < 15 ? 0 : elapsed < 30 ? 1 : elapsed < 120 ? 2 : 3;
        const phaseLabels = [
          t('costs.phase_reading', { defaultValue: 'Reading Parquet file...' }),
          t('costs.phase_extracting', { defaultValue: 'Extracting resources & cost breakdown...' }),
          t('costs.phase_writing', { defaultValue: 'Writing to local database...' }),
          t('costs.phase_finalizing', { defaultValue: 'Finalizing...' }),
        ];
        // Smooth estimated progress (never reaches 100% until done)
        const progressPct = result
          ? 100
          : Math.min(95, phase === 0 ? elapsed * 3 : phase === 1 ? 45 + (elapsed - 15) * 2 : 75 + (elapsed - 30) * 0.2);

        return (
          <div className="mt-5 rounded-2xl border border-border-light bg-surface-elevated overflow-hidden shadow-sm">
            {/* Header with database info */}
            <div className="px-5 pt-5 pb-4">
              <div className="flex items-center gap-3 mb-4">
                {result ? (
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-success-bg">
                    <CheckCircle2 size={22} className="text-semantic-success" />
                  </div>
                ) : (
                  <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
                    <Database size={20} className="text-oe-blue" />
                    <div className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-oe-blue animate-ping" />
                    <div className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-oe-blue" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-content-primary">
                      {result ? t('costs.db_installed', { defaultValue: 'Database installed successfully' }) : t('costs.db_installing', { defaultValue: 'Installing {{name}}...', name: loadingDb?.name ?? 'database' })}
                    </h3>
                    {!result && (
                      <span className="text-xs text-oe-blue font-mono tabular-nums">
                        {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-content-tertiary mt-0.5">
                    {result
                      ? t('costs.db_saved_offline', { defaultValue: 'Cost items are saved locally and available offline.' })
                      : t('costs.db_downloading', { defaultValue: 'Downloading and indexing cost items with full resource breakdown. This is a one-time setup.' })}
                  </p>
                </div>
              </div>

              {/* Progress bar — prominent, with percentage */}
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-medium text-content-secondary">
                    {result ? t('costs.phase_complete', { defaultValue: 'Complete' }) : phaseLabels[phase]}
                  </span>
                  <span className="text-xs font-semibold text-oe-blue tabular-nums">
                    {Math.round(progressPct)}%
                  </span>
                </div>
                <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                  <div
                    className={`h-full rounded-full transition-all duration-1000 ease-out ${
                      result
                        ? 'bg-semantic-success'
                        : 'bg-gradient-to-r from-oe-blue via-blue-400 to-oe-blue bg-[length:200%_100%] animate-shimmer'
                    }`}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>

              {/* Phase steps */}
              {!result && (
                <div className="flex items-center gap-1 text-2xs">
                  {[
                    t('costs.step_read', { defaultValue: 'Read' }),
                    t('costs.step_parse', { defaultValue: 'Parse' }),
                    t('costs.step_write', { defaultValue: 'Write' }),
                    t('costs.step_done', { defaultValue: 'Done' }),
                  ].map((label, i) => (
                    <div key={label} className="flex items-center gap-1">
                      <div className={`h-1.5 w-1.5 rounded-full ${
                        i < phase ? 'bg-semantic-success' : i === phase ? 'bg-oe-blue animate-pulse' : 'bg-surface-tertiary'
                      }`} />
                      <span className={i <= phase ? 'text-content-secondary font-medium' : 'text-content-quaternary'}>
                        {label}
                      </span>
                      {i < 3 && <span className="text-content-quaternary mx-0.5">&middot;</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Success result details */}
              {result && (
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <div className="rounded-lg bg-semantic-success-bg/50 px-3 py-2 text-center">
                    <div className="text-lg font-bold text-[#15803d] tabular-nums">
                      {result.imported.toLocaleString()}
                    </div>
                    <div className="text-2xs text-[#15803d]/70">{t('costs.items_installed', { defaultValue: 'items installed' })}</div>
                  </div>
                  <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                    <div className="text-lg font-bold text-content-secondary tabular-nums">
                      {result.skipped.toLocaleString()}
                    </div>
                    <div className="text-2xs text-content-tertiary">{t('costs.duplicates_skipped', { defaultValue: 'duplicates skipped' })}</div>
                  </div>
                  <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                    <div className="text-lg font-bold text-content-secondary tabular-nums">
                      {loadingDb?.currency ?? '—'}
                    </div>
                    <div className="text-2xs text-content-tertiary">{t('costs.currency', { defaultValue: 'currency' })}</div>
                  </div>
                </div>
              )}
            </div>

            {/* What's included — always visible info strip */}
            <div className="px-5 py-3 bg-surface-secondary/50 border-t border-border-light">
              <div className="flex items-center gap-4 text-2xs text-content-tertiary">
                <span className="flex items-center gap-1">
                  <Database size={10} /> {t('costs.cost_items_count', { defaultValue: '55,000+ cost items' })}
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> {t('costs.labor_rates', { defaultValue: 'Labor rates' })}
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-blue-400" /> {t('costs.equipment', { defaultValue: 'Equipment' })}
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-400" /> {t('costs.materials', { defaultValue: 'Materials' })}
                </span>
                <span className="ml-auto font-medium text-content-secondary">
                  {result ? t('costs.available_offline', { defaultValue: 'Available offline' }) : t('costs.one_time_download', { defaultValue: 'One-time download' })}
                </span>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Export Excel helper ──────────────────────────────────────────────────────

async function downloadExcelExport(): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/costs/actions/export-excel', { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || 'cost_database_export.xlsx';
  triggerDownload(blob, filename);
}

// ── Loaded Databases Section ────────────────────────────────────────────────

function LoadedDatabasesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [deletingRegion, setDeletingRegion] = useState<string | null>(null);

  // Fetch real per-region stats from backend
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats'),
    retry: false,
    refetchOnWindowFocus: true,
  });

  const totalItems = regionStats?.reduce((s, r) => s + r.count, 0) ?? 0;
  const hasData = regionStats && regionStats.length > 0;

  // Export mutation
  const exportMutation = useMutation({
    mutationFn: downloadExcelExport,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('costs.export_success', { defaultValue: 'Export complete' }),
        message: t('costs.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.export_failed', { defaultValue: 'Export failed' }),
        message: err.message,
      });
    },
  });

  // Delete single region
  const deleteRegionMutation = useMutation({
    mutationFn: (region: string) =>
      apiDelete<{ deleted: number; region: string }>(`/v1/costs/actions/clear-region/${region}`),
    onSuccess: (_data, region) => {
      removeLoadedDatabase(region);
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      setDeletingRegion(null);
      addToast({
        type: 'success',
        title: t('costs.region_cleared', { defaultValue: 'Region cleared' }),
        message: `${CWICR_DATABASES.find((d) => d.id === region)?.name ?? region} removed`,
      });
    },
    onError: (err: Error) => {
      setDeletingRegion(null);
      addToast({ type: 'error', title: t('costs.delete_failed', { defaultValue: 'Delete failed' }), message: err.message });
    },
  });

  // Clear all mutation
  const clearMutation = useMutation({
    mutationFn: () => apiDelete<{ deleted: number }>('/v1/costs/actions/clear-database?source=cwicr'),
    onSuccess: () => {
      clearLoadedDatabases();
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      setShowClearConfirm(false);
      addToast({
        type: 'success',
        title: t('costs.clear_success', { defaultValue: 'Database cleared' }),
        message: t('costs.clear_success_msg', {
          defaultValue: 'All CWICR items have been removed.',
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.clear_failed', { defaultValue: 'Clear failed' }),
        message: err.message,
      });
    },
  });

  if (!hasData) {
    return null;
  }

  const activeDbId = getActiveDatabase();

  return (
    <Card className="mb-6 animate-card-in" padding="none">
      <div className="px-6 py-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs.loaded_databases', { defaultValue: 'Loaded Databases' })}
            </h3>
            <p className="text-xs text-content-tertiary mt-0.5">
              {regionStats.length} {regionStats.length === 1 ? 'region' : 'regions'} &middot;{' '}
              {totalItems.toLocaleString()} items total
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => exportMutation.mutate()}
              loading={exportMutation.isPending}
            >
              {t('costs.export_excel', { defaultValue: 'Export Excel' })}
            </Button>
            {regionStats.length > 1 && (
              <Button
                variant="danger"
                size="sm"
                icon={<Trash2 size={14} />}
                onClick={() => setShowClearConfirm(true)}
                loading={clearMutation.isPending}
              >
                {t('costs.clear_all', { defaultValue: 'Clear All' })}
              </Button>
            )}
          </div>
        </div>

        {/* Per-region table */}
        <div className="rounded-lg border border-border-light overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-tertiary text-left">
                <th className="px-3 py-2 text-xs font-medium text-content-secondary">{t('costs.col_region', { defaultValue: 'Region' })}</th>
                <th className="px-3 py-2 text-xs font-medium text-content-secondary text-right">{t('costs.col_items', { defaultValue: 'Items' })}</th>
                <th className="px-3 py-2 text-xs font-medium text-content-secondary text-center">{t('costs.col_status', { defaultValue: 'Status' })}</th>
                <th className="px-3 py-2 text-xs font-medium text-content-secondary text-center">{t('costs.col_vector', { defaultValue: 'Vector' })}</th>
                <th className="px-3 py-2 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {regionStats.map((rs) => {
                const db = CWICR_DATABASES.find((d) => d.id === rs.region);
                const isActive = activeDbId === rs.region;
                const isDeleting = deletingRegion === rs.region;
                // Fallback labels for non-CWICR regions
                const regionLabel = db?.name ?? (rs.region === 'CUSTOM' ? 'My Database' : rs.region === 'DACH' ? 'DACH Region' : rs.region);
                const regionFlag = db?.flagId ?? (rs.region === 'DACH' ? 'de' : undefined);
                return (
                  <tr key={rs.region} className="hover:bg-surface-secondary/50 transition-colors">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        {regionFlag ? <MiniFlag code={regionFlag} /> : (
                          <span className="flex h-5 w-8 items-center justify-center rounded-sm bg-surface-tertiary text-2xs font-medium text-content-tertiary">
                            {rs.region.slice(0, 2)}
                          </span>
                        )}
                        <div>
                          <span className="text-sm font-medium text-content-primary">
                            {regionLabel}
                          </span>
                          {db && (
                            <span className="text-2xs text-content-tertiary ml-1.5">
                              {db.currency}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-sm font-semibold text-content-primary">
                      {rs.count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      {isActive ? (
                        <Badge variant="blue" size="sm">
                          <Star size={10} className="fill-current mr-0.5" /> Active
                        </Badge>
                      ) : (
                        <Badge variant="success" size="sm">
                          <CheckCircle2 size={10} className="mr-0.5" /> Loaded
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <span className="text-2xs text-content-quaternary">--</span>
                    </td>
                    <td className="px-2 py-2.5">
                      {isDeleting ? (
                        <Loader2 size={14} className="animate-spin text-semantic-error mx-auto" />
                      ) : (
                        <button
                          onClick={() => {
                            setDeletingRegion(rs.region);
                            deleteRegionMutation.mutate(rs.region);
                          }}
                          title={`Delete ${db?.name ?? rs.region}`}
                          className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors mx-auto"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Clear all confirmation */}
        {showClearConfirm && (
          <div className="mt-4 rounded-xl border border-semantic-error/20 bg-semantic-error-bg/30 p-4">
            <p className="text-sm font-medium text-semantic-error mb-1">
              Clear all {regionStats.length} databases?
            </p>
            <p className="text-xs text-content-secondary mb-3">
              This will permanently remove all {totalItems.toLocaleString()} CWICR cost items. You
              can re-import them later.
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="danger"
                size="sm"
                onClick={() => clearMutation.mutate()}
                loading={clearMutation.isPending}
              >
                {t('costs.yes_clear_all', { defaultValue: 'Yes, Clear All' })}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowClearConfirm(false)}
                disabled={clearMutation.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

// ── Vector Database Import Section ───────────────────────────────────────────

interface VectorStatus {
  connected: boolean;
  backend?: string;
  engine?: string;
  url?: string;
  error?: string;
  collections?: string[];
  cost_collection?: { vectors_count: number; points_count: number; status: string } | null;
  can_restore_snapshots?: boolean;
  can_generate_locally?: boolean;
}

interface VectorRegionStat {
  region: string;
  count: number;
}

function VectorDatabaseSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [loadingRegion, setLoadingRegion] = useState<string | null>(null);
  const [isIndexingAll, setIsIndexingAll] = useState(false);
  const [lastResult, setLastResult] = useState<{ region: string; indexed: number; duration: number } | null>(null);

  // Check vector DB status (LanceDB embedded or Qdrant)
  const { data: vectorStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['costs', 'vector', 'status'],
    queryFn: () => apiGet<VectorStatus>('/v1/costs/vector/status'),
    retry: false,
    refetchInterval: (loadingRegion || isIndexingAll) ? 5000 : false,
  });

  const isConnected = vectorStatus?.connected ?? false;

  // Per-region vector counts — only fetch when vector DB is connected
  const { data: vectorRegionStats, refetch: refetchVectorRegions } = useQuery({
    queryKey: ['costs', 'vector', 'regions'],
    queryFn: () => apiGet<VectorRegionStat[]>('/v1/costs/vector/regions').catch(() => [] as VectorRegionStat[]),
    retry: false,
    enabled: isConnected,
  });

  // Region stats for cost item counts
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats'),
    retry: false,
  });

  const hasRegions = regionStats && regionStats.length > 0;
  const totalItems = regionStats?.reduce((s, r) => s + r.count, 0) ?? 0;
  const indexedCount = vectorStatus?.cost_collection?.vectors_count ?? 0;
  const isFullyIndexed = indexedCount > 0 && indexedCount >= totalItems * 0.9;

  // Build a set of regions that already have vectors
  const vectorizedRegions = new Set(
    (vectorRegionStats ?? []).filter((r) => r.count > 0).map((r) => r.region),
  );
  const vectorCountByRegion = Object.fromEntries(
    (vectorRegionStats ?? []).map((r) => [r.region, r.count]),
  );

  // Load vectors for a specific region: route based on backend type
  const handleLoadVectors = useCallback(
    async (db: CWICRDatabase) => {
      setLoadingRegion(db.id);
      setLastResult(null);
      try {
        if (vectorStatus?.can_restore_snapshots) {
          // Qdrant: restore pre-built 3072d snapshot from GitHub
          const data = await apiPost<Record<string, unknown>>(`/v1/costs/vector/restore-snapshot/${db.id}`);
          const indexed = (data.indexed as number) ?? (data.restored ? 1 : 0);
          const duration = (data.duration_seconds as number) ?? 0;
          setLastResult({ region: db.id, indexed, duration });
          addToast({
            type: 'success',
            title: `${db.name} snapshot restored`,
            message: `Qdrant 3072d vectors restored in ${duration}s`,
          });
        } else {
          // LanceDB: try pre-built vectors from GitHub first
          try {
            const data = await apiPost<Record<string, unknown>>(`/v1/costs/vector/load-github/${db.id}`);
            const indexed = (data.indexed as number) ?? 0;
            const duration = (data.duration_seconds as number) ?? 0;
            setLastResult({ region: db.id, indexed, duration });
            addToast({
              type: 'success',
              title: `${db.name} vectors loaded`,
              message: `${indexed.toLocaleString()} vectors indexed in ${duration}s`,
            });
          } catch (err) {
            console.error('GitHub vector load failed, falling back to local generation:', err);
            // GitHub vectors not available — generate locally for this region
            const token = useAuthStore.getState().accessToken;
            const res = await fetch(`/api/v1/costs/vector/index?region=${encodeURIComponent(db.id)}`, {
              method: 'POST',
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (res.ok) {
              const data = await res.json();
              const indexed = (data.indexed as number) ?? 0;
              const duration = (data.duration_seconds as number) ?? 0;
              setLastResult({ region: db.id, indexed, duration });
              addToast({
                type: 'success',
                title: `${db.name} vectors generated`,
                message: `${indexed.toLocaleString()} vectors indexed locally in ${duration}s`,
              });
            } else {
              const errData = await res.json().catch(() => ({ detail: 'Indexing failed' }));
              addToast({
                type: 'error',
                title: `Failed to index ${db.name} vectors`,
                message: errData.detail ?? 'Vector generation failed',
              });
            }
          }
        }
      } catch (err) {
        addToast({
          type: 'error',
          title: `Failed to load ${db.name} vectors`,
          message: err instanceof Error ? err.message : t('common.connection_error', { defaultValue: 'Connection error' }),
        });
      } finally {
        refetchStatus();
        refetchVectorRegions();
        queryClient.invalidateQueries({ queryKey: ['costs', 'vector'] });
        setLoadingRegion(null);
      }
    },
    [addToast, refetchStatus, refetchVectorRegions, queryClient, t, vectorStatus?.can_restore_snapshots],
  );

  // Generate vectors locally for all regions
  const handleVectorizeAll = useCallback(async () => {
    setIsIndexingAll(true);
    setLastResult(null);
    try {
      const token = useAuthStore.getState().accessToken;
      const res = await fetch('/api/v1/costs/vector/index', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setLastResult({ region: 'all', indexed: data.indexed, duration: data.duration_seconds });
        addToast({
          type: 'success',
          title: 'Vector index created',
          message: `${data.indexed.toLocaleString()} items indexed in ${data.duration_seconds}s`,
        });
        refetchStatus();
        refetchVectorRegions();
        queryClient.invalidateQueries({ queryKey: ['costs', 'vector'] });
      } else {
        const err = await res.json().catch(() => ({ detail: 'Indexing failed' }));
        addToast({ type: 'error', title: t('costs.indexing_failed', { defaultValue: 'Indexing failed' }), message: err.detail });
      }
    } catch {
      addToast({ type: 'error', title: t('common.connection_error', { defaultValue: 'Connection error' }) });
    } finally {
      setIsIndexingAll(false);
    }
  }, [addToast, refetchStatus, refetchVectorRegions, queryClient, t]);

  const isLoading = loadingRegion !== null || isIndexingAll;

  return (
    <Card className="mb-6" padding="none">
      <div className="px-6 py-5">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 text-white">
            <Sparkles size={18} />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                CWICR Vector Database — AI Semantic Search
              </h3>
              {isConnected ? (
                <>
                  <span className="flex items-center gap-1 text-2xs font-medium text-semantic-success">
                    <span className="h-1.5 w-1.5 rounded-full bg-semantic-success" />
                    Ready
                  </span>
                  {vectorStatus?.backend === 'qdrant' ? (
                    <Badge variant="success" size="sm" className="text-2xs px-1.5 py-0">Qdrant (3072d)</Badge>
                  ) : (
                    <Badge variant="blue" size="sm" className="text-2xs px-1.5 py-0">LanceDB (384d)</Badge>
                  )}
                </>
              ) : (
                <span className="flex items-center gap-1 text-2xs font-medium text-content-quaternary">
                  <span className="h-1.5 w-1.5 rounded-full bg-content-quaternary" />
                  Offline
                </span>
              )}
            </div>
            <p className="text-xs text-content-tertiary">
              55,719 vectors per region &middot;{' '}
              {vectorStatus?.backend === 'qdrant' ? '3072d embeddings (text-embedding-3-large)' : '384d embeddings (all-MiniLM-L6-v2)'}{' '}
              &middot; by Data Driven Construction
            </p>
          </div>
        </div>

        <p className="text-xs text-content-secondary mb-4">
          Select your region to generate AI vector embeddings. Enables semantic
          search — find cost items by meaning, not just keywords. E.g. &quot;concrete wall&quot; finds
          &quot;reinforced partition C30/37&quot;.
        </p>

        {/* Not connected state */}
        {!isConnected ? (
          <div className="rounded-xl border border-amber-200/40 bg-amber-50/30 dark:bg-amber-500/5 dark:border-amber-500/10 p-4">
            <p className="text-sm font-medium text-amber-700 dark:text-amber-400 mb-2">
              Vector search not available
            </p>
            <div className="space-y-2 text-xs text-content-tertiary">
              <div>
                <strong className="text-content-secondary">Option A — Qdrant (best quality, 3072d):</strong><br/>
                <code className="text-2xs bg-surface-secondary px-1 py-0.5 rounded">docker run -p 6333:6333 qdrant/qdrant</code>
              </div>
              <div>
                <strong className="text-content-secondary">Option B — LanceDB (lightweight, 384d):</strong><br/>
                <code className="text-2xs bg-surface-secondary px-1 py-0.5 rounded">pip install lancedb sentence-transformers</code>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Region grid — same style as CWICR */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-5">
              {CWICR_DATABASES.map((db) => {
                const isLoadingThis = loadingRegion === db.id;
                const isVectorized = vectorizedRegions.has(db.id);
                const vecCount = vectorCountByRegion[db.id] ?? 0;

                return (
                  <div
                    key={db.id}
                    className={`
                      relative flex flex-col rounded-xl
                      border transition-all duration-normal ease-oe
                      ${
                        isVectorized
                          ? 'border-purple-400/40 bg-purple-50/20 dark:bg-purple-500/5'
                          : isLoadingThis
                            ? 'border-purple-400/40 bg-purple-50/30 dark:bg-purple-500/10'
                            : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary'
                      }
                      ${isLoading && !isLoadingThis ? 'opacity-40 pointer-events-none' : ''}
                    `}
                  >
                    <button
                      onClick={() => handleLoadVectors(db)}
                      disabled={isLoading}
                      className="flex items-center gap-3 px-3.5 py-3 text-left active:scale-[0.98] transition-transform"
                    >
                      <MiniFlag code={db.flagId} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-content-primary">
                            {db.name}
                          </span>
                          {isVectorized && (
                            <CheckCircle2
                              size={14}
                              className="text-purple-500 shrink-0"
                            />
                          )}
                        </div>
                        <div className="text-2xs text-content-tertiary">
                          {db.city} &middot; {db.lang} &middot; {db.currency}
                        </div>
                        <div className="flex items-center gap-1.5 mt-1">
                          {isVectorized ? (
                            <span className="text-2xs text-purple-600 font-medium">
                              {vecCount.toLocaleString()} vectors
                            </span>
                          ) : (
                            <span className="text-2xs text-content-quaternary">55,719 vectors</span>
                          )}
                          <Badge variant="blue" size="sm" className="text-2xs px-1.5 py-0">
                            AI
                          </Badge>
                        </div>
                      </div>
                      {isLoadingThis && (
                        <Loader2 size={16} className="animate-spin text-purple-500 shrink-0" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="rounded-lg bg-surface-secondary p-3 text-center">
                <div className="text-lg font-bold tabular-nums text-content-primary">
                  {totalItems.toLocaleString()}
                </div>
                <div className="text-2xs text-content-tertiary">Cost items</div>
              </div>
              <div className="rounded-lg bg-surface-secondary p-3 text-center">
                <div className={`text-lg font-bold tabular-nums ${indexedCount > 0 ? 'text-purple-600' : 'text-content-tertiary'}`}>
                  {indexedCount.toLocaleString()}
                </div>
                <div className="text-2xs text-content-tertiary">Vectors indexed</div>
              </div>
              <div className="rounded-lg bg-surface-secondary p-3 text-center">
                <div className={`text-lg font-bold ${isFullyIndexed ? 'text-semantic-success' : 'text-content-tertiary'}`}>
                  {isFullyIndexed ? '100%' : indexedCount > 0 ? `${Math.round((indexedCount / Math.max(totalItems, 1)) * 100)}%` : '0%'}
                </div>
                <div className="text-2xs text-content-tertiary">Coverage</div>
              </div>
            </div>

            {/* Last result */}
            {lastResult && (
              <div className="rounded-lg bg-semantic-success-bg/40 border border-semantic-success/20 px-4 py-3 mb-4">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={14} className="text-semantic-success" />
                  <span className="text-xs font-medium text-[#15803d]">
                    {lastResult.indexed.toLocaleString()} vectors indexed in {lastResult.duration}s
                    {lastResult.region !== 'all' && ` (${CWICR_DATABASES.find((d) => d.id === lastResult.region)?.name ?? lastResult.region})`}
                  </span>
                </div>
              </div>
            )}

            {/* Generate locally fallback */}
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                icon={isIndexingAll ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                onClick={handleVectorizeAll}
                disabled={!hasRegions || isLoading}
              >
                {isIndexingAll
                  ? 'Generating Embeddings...'
                  : isFullyIndexed
                    ? 'Re-index All Regions'
                    : 'Generate All Regions'}
              </Button>
              <span className="text-2xs text-content-tertiary">
                {vectorStatus?.backend === 'qdrant'
                  ? 'Model: text-embedding-3-large (3072d) \u00b7 Qdrant snapshots from GitHub'
                  : 'Model: all-MiniLM-L6-v2 (384d) \u00b7 Runs on your machine \u00b7 No API key'}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Tech info strip */}
      <div className="px-6 py-2.5 bg-surface-secondary/50 border-t border-border-light">
        <div className="flex items-center gap-4 text-2xs text-content-quaternary">
          {vectorStatus?.backend === 'qdrant' ? (
            <>
              <span>Qdrant</span>
              <span>&middot;</span>
              <span>text-embedding-3-large</span>
              <span>&middot;</span>
              <span>3072d cosine similarity</span>
              <span>&middot;</span>
              <span>Snapshot restore</span>
            </>
          ) : (
            <>
              <span>LanceDB embedded</span>
              <span>&middot;</span>
              <span>FastEmbed ONNX</span>
              <span>&middot;</span>
              <span>384d cosine similarity</span>
              <span>&middot;</span>
              <span>No Docker required</span>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function ImportDatabasePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      const type = getFileType(file.name);
      if (!type) {
        addToast({
          type: 'error',
          title: t('costs.import_unsupported_format', {
            defaultValue: 'Unsupported file format',
          }),
          message: t('costs.import_supported_hint', {
            defaultValue: 'Please upload an Excel (.xlsx) or CSV (.csv) file.',
          }),
        });
        return;
      }

      // 10MB limit
      if (file.size > 10 * 1024 * 1024) {
        addToast({
          type: 'error',
          title: t('costs.import_file_too_large', { defaultValue: 'File too large' }),
          message: t('costs.import_max_size', { defaultValue: 'Maximum file size is 10 MB.' }),
        });
        return;
      }

      setSelectedFile(file);
      setPreview({
        name: file.name,
        size: formatFileSize(file.size),
        type,
      });
      setResult(null);
    },
    [addToast, t],
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleFileInput = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const importMutation = useMutation({
    mutationFn: () => {
      if (!selectedFile) throw new Error('No file selected');
      return uploadCostFile(selectedFile);
    },
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      if (data.imported > 0) {
        addToast({
          type: 'success',
          title: t('costs.import_success', {
            defaultValue: 'Import complete',
          }),
          message: `${data.imported} items imported successfully.`,
        });
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.import_failed', { defaultValue: 'Import failed' }),
        message: err.message,
      });
    },
  });

  const handleReset = useCallback(() => {
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        className="mb-4"
        items={[
          { label: t('costs.title', 'Cost Database'), to: '/costs' },
          { label: t('costs.import_title', 'Import Cost Database') },
        ]}
      />

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('costs.import_title', { defaultValue: 'Import Cost Database' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('costs.import_subtitle', {
            defaultValue: 'Load a pricing database or upload your own file.',
          })}
        </p>
      </div>

      {/* DDC CWICR Database -- 11 regional databases */}
      <Card className="mb-6" padding="none">
        <div className="px-6 pt-5 pb-2">
          <div className="flex items-center gap-3 mb-1">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue text-white">
              <Database size={18} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-content-primary">
                CWICR Construction Cost Database
              </h3>
              <p className="text-xs text-content-tertiary">
                55,719 items per region &middot; 85 fields &middot; 11 databases &middot; by
                Data Driven Construction
              </p>
            </div>
          </div>
        </div>
        <div className="px-6 pb-5">
          <p className="text-xs text-content-secondary mb-4">
            Select your region to load the professional pricing database. One click -- instant
            access to 55,000+ construction cost items with labor, materials, and equipment rates.
            USA and UK databases are downloaded from GitHub if not available locally.
          </p>
          <CWICRDatabaseGrid onLoadDatabase={handleFile} />
        </div>
      </Card>

      {/* Vector Database section — shown prominently */}
      <VectorDatabaseSection />

      {/* Loaded Databases section */}
      <LoadedDatabasesSection />

      {/* Divider */}
      <div className="flex items-center gap-3 mb-6">
        <div className="h-px flex-1 bg-border-light" />
        <span className="text-xs font-medium text-content-tertiary uppercase tracking-wider">
          {t('costs.or_upload_own', { defaultValue: 'or upload your own file' })}
        </span>
        <div className="h-px flex-1 bg-border-light" />
      </div>

      {/* Import result summary */}
      {result && (
        <Card className="mb-6 animate-card-in">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              {result.errors.length === 0 && result.imported > 0 ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-success-bg">
                  <CheckCircle2 size={20} className="text-semantic-success" />
                </div>
              ) : result.imported === 0 ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error-bg">
                  <XCircle size={20} className="text-semantic-error" />
                </div>
              ) : (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-warning-bg">
                  <AlertTriangle size={20} className="text-semantic-warning" />
                </div>
              )}
              <div>
                <h3 className="text-base font-semibold text-content-primary">
                  {t('costs.import_complete', { defaultValue: 'Import Complete' })}
                </h3>
                <p className="text-sm text-content-secondary">
                  {result.total_rows}{' '}
                  {t('costs.import_rows_processed', { defaultValue: 'rows processed' })}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-semantic-success-bg/50 px-4 py-3 text-center">
                <div className="text-2xl font-bold text-[#15803d]">{result.imported}</div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_imported', { defaultValue: 'Imported' })}
                </div>
              </div>
              <div className="rounded-xl bg-surface-secondary px-4 py-3 text-center">
                <div className="text-2xl font-bold text-content-secondary">{result.skipped}</div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_skipped', { defaultValue: 'Skipped' })}
                </div>
              </div>
              <div className="rounded-xl bg-semantic-error-bg/50 px-4 py-3 text-center">
                <div className="text-2xl font-bold text-semantic-error">
                  {result.errors.length}
                </div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_errors', { defaultValue: 'Errors' })}
                </div>
              </div>
            </div>

            {/* Error details (first 5) */}
            {result.errors.length > 0 && (
              <div className="rounded-lg border border-semantic-error/20 bg-semantic-error-bg/30 p-3">
                <p className="text-xs font-medium text-semantic-error mb-2">
                  {t('costs.import_error_details', { defaultValue: 'Error details' })}
                </p>
                <div className="space-y-1.5">
                  {result.errors.slice(0, 5).map((err, i) => (
                    <p key={i} className="text-xs text-content-secondary">
                      <span className="font-mono text-semantic-error">
                        {t('costs.import_row', { defaultValue: 'Row' })} {err.row}
                      </span>
                      : {err.error}
                    </p>
                  ))}
                  {result.errors.length > 5 && (
                    <p className="text-xs text-content-tertiary">
                      ...
                      {t('costs.import_and_more', {
                        defaultValue: 'and {{count}} more errors',
                        count: result.errors.length - 5,
                      })}
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="flex items-center gap-3 pt-1">
              <Button variant="secondary" onClick={handleReset}>
                {t('costs.import_another', { defaultValue: 'Import Another' })}
              </Button>
              <Button variant="primary" onClick={() => navigate('/costs')}>
                {t('costs.import_go_to_database', { defaultValue: 'Go to Cost Database' })}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Upload area */}
      {!result && (
        <>
          {/* Supported formats */}
          <Card className="mb-6">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle">
                <Database size={20} className="text-oe-blue" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('costs.import_formats_title', { defaultValue: 'Supported formats' })}
                </h3>
                <ul className="mt-2 space-y-1.5 text-sm text-content-secondary">
                  <li className="flex items-center gap-2">
                    <FileSpreadsheet size={14} className="text-[#15803d] shrink-0" />
                    {t('costs.import_format_excel', {
                      defaultValue:
                        'Excel (.xlsx) with columns: Code, Description, Unit, Rate',
                    })}
                  </li>
                  <li className="flex items-center gap-2">
                    <FileSpreadsheet size={14} className="text-oe-blue shrink-0" />
                    {t('costs.import_format_csv', {
                      defaultValue: 'CSV (.csv) with the same columns',
                    })}
                  </li>
                </ul>
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('costs.import_columns_hint', {
                    defaultValue:
                      'Columns are auto-detected. Accepted headers: Code, Description, Unit, Rate/Price/Cost, Currency, DIN 276/Classification.',
                  })}
                </p>
              </div>
            </div>
          </Card>

          {/* Drag & drop zone */}
          <Card padding="none" className="overflow-hidden">
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center px-8 py-16 cursor-pointer transition-all duration-normal ease-oe ${
                isDragging
                  ? 'bg-oe-blue-subtle border-2 border-dashed border-oe-blue'
                  : selectedFile
                    ? 'bg-surface-secondary'
                    : 'bg-surface-elevated hover:bg-surface-secondary border-2 border-dashed border-border-light hover:border-border'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.csv,.xls"
                onChange={handleFileInput}
                className="hidden"
              />

              {selectedFile && preview ? (
                <div className="flex flex-col items-center gap-3 animate-fade-in">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue-subtle">
                    <FileSpreadsheet size={28} className="text-oe-blue" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-semibold text-content-primary">{preview.name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="blue" size="sm">
                        {preview.type === 'excel' ? 'Excel' : 'CSV'}
                      </Badge>
                      <span className="text-xs text-content-tertiary">{preview.size}</span>
                    </div>
                  </div>
                  <p className="text-xs text-content-tertiary mt-1">
                    {t('costs.import_click_to_change', {
                      defaultValue: 'Click to choose a different file',
                    })}
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <div
                    className={`flex h-14 w-14 items-center justify-center rounded-2xl transition-colors duration-normal ${
                      isDragging
                        ? 'bg-oe-blue text-white'
                        : 'bg-surface-secondary text-content-tertiary'
                    }`}
                  >
                    <Upload size={28} />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-semibold text-content-primary">
                      {isDragging
                        ? t('costs.import_drop_here', { defaultValue: 'Drop your file here' })
                        : t('costs.import_drop_or_click', {
                            defaultValue: 'Drop your file here or click to browse',
                          })}
                    </p>
                    <p className="mt-1 text-xs text-content-tertiary">
                      {t('costs.import_accepted', {
                        defaultValue: 'Excel (.xlsx) or CSV (.csv) - max 10 MB',
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Actions */}
          {selectedFile && (
            <div className="mt-6 flex items-center justify-end gap-3 animate-fade-in">
              <Button variant="secondary" onClick={handleReset}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => importMutation.mutate()}
                loading={importMutation.isPending}
                icon={
                  importMutation.isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Upload size={16} />
                  )
                }
              >
                {importMutation.isPending
                  ? t('costs.import_importing', { defaultValue: 'Importing...' })
                  : t('costs.import_all', { defaultValue: 'Import All' })}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
