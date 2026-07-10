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
  Globe,
  BookOpen,
} from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, ConfirmDialog, CountryFlag, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiGet, apiPost, apiDelete, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { formatFileSize } from '@/shared/lib/formatters';
import { COMMON_CURRENCIES } from '@/features/boq/boqHelpers';
import { fetchCostCatalogs, type CostCatalog } from './api';

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
  catalog?: string | null;
  /** Target catalog the rows landed in (existing or created inline). */
  catalog_id?: string | null;
  /** Currency of the target catalog - the default for rows without one. */
  catalog_currency?: string | null;
  /** Rows whose own currency differs from the catalog currency. Imported
   *  as-is (never silently rewritten) - a warning, not a block. */
  mixed_currency_count?: number;
}

// Result of the column-mapping preview endpoint. Drives the mapping panel:
// the user maps each canonical target field to one of the raw file headers
// before committing the import.
interface PreviewResult {
  headers: string[];
  sample_rows: string[][];
  suggested_map: Record<string, string>;
  target_fields: string[];
  required_fields: string[];
  /** Whether the auto-detected mapping found a currency column. When false,
   *  creating a NEW catalog requires an explicit catalog currency. */
  has_currency_column?: boolean;
}

// Sentinel used by the per-field <select> to mean "this canonical field has
// no source column". Kept out of the submitted column_map.
const NOT_MAPPED = '';

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

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Ask the backend to inspect the uploaded file: it returns the raw headers, a
 * few sample rows and a suggested canonical-field -> header mapping. Used to
 * drive the column-mapping panel before the actual import.
 */
async function previewCostFile(file: File): Promise<PreviewResult> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/api/v1/costs/import/preview/', {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Preview failed';
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json() as Promise<PreviewResult>;
}

/** Target-catalog options for `uploadCostFile`. Pass `catalogId` to import
 *  into an EXISTING catalog, or `catalogName` (+ `catalogCurrency` when the
 *  file has no mapped currency column) to create one inline. Mutually
 *  exclusive - the backend rejects both at once. */
interface UploadCostFileOptions {
  columnMap?: Record<string, string>;
  catalogId?: string;
  catalogName?: string;
  catalogCurrency?: string;
}

/**
 * Import a cost file. When `columnMap` is supplied it is sent as a JSON
 * `column_map` (canonical field -> raw header) so the backend uses the user's
 * explicit mapping instead of re-guessing. The catalog options route the
 * imported rows into a user catalog. Everything is optional so the legacy
 * auto-detect path (no map, no catalog) keeps working as a fallback.
 */
async function uploadCostFile(
  file: File,
  options: UploadCostFileOptions = {},
): Promise<ImportResult> {
  const { columnMap, catalogId, catalogName, catalogCurrency } = options;
  const formData = new FormData();
  formData.append('file', file);
  if (columnMap && Object.keys(columnMap).length > 0) {
    formData.append('column_map', JSON.stringify(columnMap));
  }
  if (catalogId) {
    formData.append('catalog_id', catalogId);
  } else if (catalogName && catalogName.trim()) {
    formData.append('catalog_name', catalogName.trim());
    if (catalogCurrency && catalogCurrency.trim()) {
      formData.append('catalog_currency', catalogCurrency.trim().toUpperCase());
    }
  }

  const response = await fetch('/api/v1/costs/import/file/', {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Upload failed';
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ImportResult>;
}

// Human-readable label + helper text per canonical target field, all i18n.
// Used by the mapping panel rows.
function useTargetFieldMeta() {
  const { t } = useTranslation();
  return (field: string): { label: string; hint: string } => {
    switch (field) {
      case 'code':
        return {
          label: t('costs_import.field_code', { defaultValue: 'Code' }),
          hint: t('costs_import.field_code_hint', { defaultValue: 'Item / position number' }),
        };
      case 'description':
        return {
          label: t('costs_import.field_description', { defaultValue: 'Description' }),
          hint: t('costs_import.field_description_hint', { defaultValue: 'What the cost item is' }),
        };
      case 'unit':
        return {
          label: t('costs_import.field_unit', { defaultValue: 'Unit' }),
          hint: t('costs_import.field_unit_hint', { defaultValue: 'm, m2, m3, pcs, h ...' }),
        };
      case 'rate':
        return {
          label: t('costs_import.field_rate', { defaultValue: 'Rate' }),
          hint: t('costs_import.field_rate_hint', { defaultValue: 'Unit price / cost' }),
        };
      case 'currency':
        return {
          label: t('costs_import.field_currency', { defaultValue: 'Currency' }),
          hint: t('costs_import.field_currency_hint', { defaultValue: 'EUR, USD, GBP ...' }),
        };
      case 'classification':
        return {
          label: t('costs_import.field_classification', { defaultValue: 'Classification' }),
          hint: t('costs_import.field_classification_hint', {
            defaultValue: 'DIN 276 / NRM / MasterFormat code',
          }),
        };
      default:
        return { label: field, hint: '' };
    }
  };
}

// ── File Preview Info ────────────────────────────────────────────────────────

interface FilePreview {
  name: string;
  size: string;
  type: 'excel' | 'csv';
}

// `formatFileSize` lives in `@/shared/lib/formatters` — same implementation,
// shared with the AI and Takeoff surfaces. Imported above.

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
  { id: 'ZH_CHINA', name: 'China', city: 'National', lang: 'Chinese', currency: 'CNY', flagId: 'cn', parquetName: 'ZH_CHINA' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in', parquetName: 'HI_MUMBAI' },
  // Added 2026-04-28 — DDC CWICR repo grew from 11 to 30 country folders.
  { id: 'AU_SYDNEY', name: 'Australia', city: 'Sydney', lang: 'English', currency: 'AUD', flagId: 'au', parquetName: 'AU_SYDNEY' },
  { id: 'NZ_AUCKLAND', name: 'New Zealand', city: 'Auckland', lang: 'English', currency: 'NZD', flagId: 'nz', parquetName: 'NZ_AUCKLAND' },
  { id: 'IT_ROME', name: 'Italy', city: 'Rome', lang: 'Italiano', currency: 'EUR', flagId: 'it', parquetName: 'IT_ROME' },
  { id: 'NL_AMSTERDAM', name: 'Netherlands', city: 'Amsterdam', lang: 'Nederlands', currency: 'EUR', flagId: 'nl', parquetName: 'NL_AMSTERDAM' },
  { id: 'PL_WARSAW', name: 'Poland', city: 'Warsaw', lang: 'Polski', currency: 'PLN', flagId: 'pl', parquetName: 'PL_WARSAW' },
  { id: 'CS_PRAGUE', name: 'Czech Republic', city: 'Prague', lang: 'Cestina', currency: 'CZK', flagId: 'cz', parquetName: 'CS_PRAGUE' },
  { id: 'HR_ZAGREB', name: 'Croatia', city: 'Zagreb', lang: 'Hrvatski', currency: 'EUR', flagId: 'hr', parquetName: 'HR_ZAGREB' },
  { id: 'BG_SOFIA', name: 'Bulgaria', city: 'Sofia', lang: 'Balgarski', currency: 'BGN', flagId: 'bg', parquetName: 'BG_SOFIA' },
  { id: 'RO_BUCHAREST', name: 'Romania', city: 'Bucharest', lang: 'Romana', currency: 'RON', flagId: 'ro', parquetName: 'RO_BUCHAREST' },
  { id: 'SV_STOCKHOLM', name: 'Sweden', city: 'Stockholm', lang: 'Svenska', currency: 'SEK', flagId: 'se', parquetName: 'SV_STOCKHOLM' },
  { id: 'TR_NATIONAL', name: 'Türkiye', city: 'National', lang: 'Türkçe', currency: 'TRY', flagId: 'tr', parquetName: 'TR_NATIONAL' },
  { id: 'JA_TOKYO', name: 'Japan', city: 'Tokyo', lang: 'Nihongo', currency: 'JPY', flagId: 'jp', parquetName: 'JA_TOKYO' },
  { id: 'KO_SEOUL', name: 'South Korea', city: 'Seoul', lang: 'Hangugeo', currency: 'KRW', flagId: 'kr', parquetName: 'KO_SEOUL' },
  { id: 'TH_BANGKOK', name: 'Thailand', city: 'Bangkok', lang: 'Thai', currency: 'THB', flagId: 'th', parquetName: 'TH_BANGKOK' },
  { id: 'VI_HANOI', name: 'Vietnam', city: 'Hanoi', lang: 'Tieng Viet', currency: 'VND', flagId: 'vn', parquetName: 'VI_HANOI' },
  { id: 'ID_JAKARTA', name: 'Indonesia', city: 'Jakarta', lang: 'Bahasa Indonesia', currency: 'IDR', flagId: 'id', parquetName: 'ID_JAKARTA' },
  { id: 'MX_MEXICOCITY', name: 'Mexico', city: 'Mexico City', lang: 'Espanol', currency: 'MXN', flagId: 'mx', parquetName: 'MX_MEXICOCITY' },
  { id: 'ZA_JOHANNESBURG', name: 'South Africa', city: 'Johannesburg', lang: 'English', currency: 'ZAR', flagId: 'za', parquetName: 'ZA_JOHANNESBURG' },
  { id: 'NG_LAGOS', name: 'Nigeria', city: 'Lagos', lang: 'English', currency: 'NGN', flagId: 'ng', parquetName: 'NG_LAGOS' },
  // Authentic national / regional official bases - loaded from the local
  // WORLD_COST_BASES parquet (official government sources), not GitHub snapshots.
  { id: 'BR_NATIONAL', name: 'Brazil (SINAPI)', city: 'National', lang: 'Portugues', currency: 'BRL', flagId: 'br', parquetName: 'BR' },
  { id: 'ES_ANDALUCIA', name: 'Spain (BCCA)', city: 'Andalucia', lang: 'Espanol', currency: 'EUR', flagId: 'es', parquetName: 'ES_ANDALUCIA' },
  { id: 'IT_TOSCANA', name: 'Italy (Toscana)', city: 'Toscana', lang: 'Italiano', currency: 'EUR', flagId: 'it', parquetName: 'IT_TOSCANA' },
  { id: 'VN_NATIONAL', name: 'Vietnam (Dinh Muc)', city: 'National', lang: 'Tieng Viet', currency: 'VND', flagId: 'vn', parquetName: 'VN' },
  { id: 'ID_NATIONAL', name: 'Indonesia (AHSP)', city: 'National', lang: 'Bahasa Indonesia', currency: 'IDR', flagId: 'id', parquetName: 'ID' },
  { id: 'GR_NATIONAL', name: 'Greece (GGDE)', city: 'National', lang: 'Ellinika', currency: 'EUR', flagId: 'gr', parquetName: 'GR' },
];

// Databases that may only be available via GitHub download (not in local DDC_Toolkit).
// All 19 regions added 2026-04-28 are GitHub-only — they were never shipped in the
// local DDC_Toolkit/pricing/data/excel directory, so the resolver must fall through
// to the GitHub-cache path on first load.
const GITHUB_ONLY_DBS = new Set([
  'UK_GBP',
  'USA_USD',
  'AU_SYDNEY',
  'NZ_AUCKLAND',
  'IT_ROME',
  'NL_AMSTERDAM',
  'PL_WARSAW',
  'CS_PRAGUE',
  'HR_ZAGREB',
  'BG_SOFIA',
  'RO_BUCHAREST',
  'SV_STOCKHOLM',
  'JA_TOKYO',
  'KO_SEOUL',
  'TH_BANGKOK',
  'VI_HANOI',
  'ID_JAKARTA',
  'MX_MEXICOCITY',
  'ZA_JOHANNESBURG',
  'NG_LAGOS',
]);

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

  // The timeout-recovery poll below can run for ~a minute after a slow import.
  // If the user navigates away from /costs/import during that window we must
  // not keep polling and then setState on an unmounted component.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Region filter — added 2026-04-28 when the registry grew from 11 to 30
  // entries. Without it the grid scrolls past one viewport on small laptops.
  const [regionQuery, setRegionQuery] = useState('');
  const filteredDatabases = (() => {
    const q = regionQuery.trim().toLowerCase();
    if (!q) return CWICR_DATABASES;
    return CWICR_DATABASES.filter(
      (db) =>
        db.name.toLowerCase().includes(q) ||
        db.city.toLowerCase().includes(q) ||
        db.currency.toLowerCase().includes(q) ||
        db.lang.toLowerCase().includes(q) ||
        db.id.toLowerCase().includes(q),
    );
  })();

  // Sync loaded state with actual backend data
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/'),
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
        // A regional CWICR import reads a ~40 MB parquet, expands 900K rows to
        // 55K items and bulk-loads them — tens of seconds, well past the 30s
        // default abort. Opt into the 5-min long-running budget (see api.ts) so
        // the request waits for the backend instead of aborting mid-import and
        // showing a false "Request timed out" (GitHub #171).
        const data = await apiPost<Record<string, unknown>>(
          `/v1/costs/load-cwicr/${db.id}`,
          undefined,
          { longRunning: true },
        );

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
        apiPost('/v1/costs/vector/index/').catch((err) => {
          if (import.meta.env.DEV) console.error('Vector indexing failed (non-critical):', err);
        });
      } catch (err: unknown) {
        // A regional import is a long single request (read parquet, expand to
        // ~55K items, bulk-load). On a slow machine it can outrun even the
        // 5-min long-running budget and the client aborts - but the server
        // keeps going and commits. Before crying failure, poll the backend for
        // up to ~a minute: if the region lands, the load actually succeeded and
        // we show success instead of a misleading timeout (GitHub #171 follow-up).
        const landed = await (async () => {
          for (let attempt = 0; attempt < 7; attempt++) {
            if (!mountedRef.current) return null;
            try {
              const stats = await apiGet<RegionStat[]>('/v1/costs/regions/stats/');
              const hit = stats.find((s) => s.region === db.id && s.count > 0);
              if (hit) return hit;
            } catch {
              // transient - keep polling
            }
            if (attempt < 6) await new Promise((r) => setTimeout(r, 10000));
          }
          return null;
        })();
        if (!mountedRef.current) return;
        if (landed) {
          setLoaded((prev) => new Set(prev).add(db.id));
          addLoadedDatabase(db.id);
          if (getLoadedDatabases().length === 1 || !getActiveDatabase()) {
            setActiveDatabase(db.id);
            setActiveDb(db.id);
          }
          setResult({ id: db.id, imported: landed.count, skipped: 0, file: '' });
          addToast({
            type: 'success',
            title: t('costs.db_installed', { defaultValue: 'Database installed successfully' }),
            message: `${landed.count.toLocaleString()} cost items imported`,
          });
          queryClient.invalidateQueries({ queryKey: ['costs'] });
          apiPost('/v1/costs/vector/index/').catch(() => {});
          return;
        }
        // The regional data is downloaded from GitHub on first load, which is
        // the usual culprit when this fails - the host is unreachable on some
        // corporate or regional networks. Prefer the backend's own detail
        // (it already names the source URL), and fall back to an actionable
        // reachability hint so the user is not left guessing. Always offer a
        // one-click Retry that re-runs the same load for this region.
        const backendDetail = err instanceof Error ? err.message : '';
        const message =
          backendDetail ||
          t('costs.load_failed_unreachable', {
            defaultValue:
              'Could not reach the data host to download this region. This is often a blocked network or a GitHub connection issue. Check your connection and that github.com is reachable, then try again.',
          });
        addToast({
          type: 'error',
          title: t('costs.load_failed_title', {
            defaultValue: 'Could not load {{name}}',
            name: db.name,
          }),
          message,
          action: {
            label: t('costs.load_failed_retry', { defaultValue: 'Retry' }),
            onClick: () => {
              void handleLoad(db);
            },
          },
        });
      } finally {
        if (mountedRef.current) setLoading(null);
      }
    },
    [addToast, t, queryClient],
  );

  return (
    <div>
      {/* Region filter (30 regions — keep grid navigable) */}
      <div className="mb-3 flex items-center gap-2">
        <input
          type="search"
          value={regionQuery}
          onChange={(e) => setRegionQuery(e.target.value)}
          placeholder={t('costs.region_filter_placeholder', {
            defaultValue: 'Filter by country, city, currency or language…',
          })}
          className="flex-1 rounded-lg bg-surface-secondary/70 px-3 py-2 text-sm text-content-primary placeholder:text-content-quaternary border border-transparent focus:border-oe-blue/40 focus:outline-none focus:bg-surface-secondary"
        />
        <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
          {t('costs.region_filter_count', {
            defaultValue: '{{shown}} of {{total}}',
            shown: filteredDatabases.length,
            total: CWICR_DATABASES.length,
          })}
        </span>
      </div>

      {/* Database grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
        {filteredDatabases.length === 0 && (
          <div className="col-span-full py-8 text-center text-sm text-content-tertiary">
            {t('costs.region_filter_no_results', {
              defaultValue: 'No regions match "{{q}}"',
              q: regionQuery,
            })}
          </div>
        )}
        {filteredDatabases.map((db) => {
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
                    <div className="text-lg font-bold text-semantic-success tabular-nums">
                      {result.imported.toLocaleString()}
                    </div>
                    <div className="text-2xs text-semantic-success/70">{t('costs.items_installed', { defaultValue: 'items installed' })}</div>
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

  const response = await fetch('/api/v1/costs/actions/export-excel/', { method: 'GET', headers });
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const utf8Name = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  // A malformed filename* (bad percent-encoding) must not turn a successful
  // download into an error toast - fall back to the plain filename match.
  let decodedName: string | undefined;
  try {
    decodedName = utf8Name ? decodeURIComponent(utf8Name) : undefined;
  } catch {
    decodedName = undefined;
  }
  const filename =
    decodedName ||
    disposition?.match(/filename="?([^";]+)"?/)?.[1] ||
    'cost_database_export.xlsx';
  triggerDownload(blob, filename);
}

// ── Loaded Databases Section ────────────────────────────────────────────────

function LoadedDatabasesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [deletingRegion, setDeletingRegion] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  // Fetch real per-region stats from backend.
  // ``.catch(() => [])`` so a transient 401/500 doesn't leave ``data`` undefined
  // forever — the section still renders an empty-state row instead of vanishing.
  const { data: regionStats, isLoading } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/').catch(() => [] as RegionStat[]),
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
    mutationFn: () => apiDelete<{ deleted: number }>('/v1/costs/actions/clear-database/?source=cwicr'),
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

  const activeDbId = getActiveDatabase();
  const regionCount = regionStats?.length ?? 0;

  return (
    <Card className="mb-6 animate-card-in" padding="none">
      <div className="px-6 py-5">
        {/* Header — always rendered so users always have a way to manage installed DBs */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs.loaded_databases', { defaultValue: 'Installed Databases' })}
            </h3>
            <p className="text-xs text-content-tertiary mt-0.5">
              {isLoading
                ? t('costs.loaded_loading', { defaultValue: 'Loading installed databases...' })
                : hasData
                  ? `${regionCount} ${regionCount === 1 ? t('costs.region_singular', { defaultValue: 'region' }) : t('costs.region_plural', { defaultValue: 'regions' })} · ${totalItems.toLocaleString()} ${t('costs.items_total', { defaultValue: 'items total' })}`
                  : t('costs.no_databases_installed', {
                      defaultValue: 'No databases installed yet. Pick a region above to install.',
                    })}
            </p>
          </div>
          {hasData && (
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
              {regionCount > 1 && (
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
          )}
        </div>

        {/* Loading skeleton */}
        {isLoading && !regionStats && (
          <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
            <div className="flex items-center gap-2 text-xs text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('costs.loaded_fetching', { defaultValue: 'Fetching installed databases...' })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !hasData && (
          <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary/20 px-4 py-6 text-center">
            <Database size={20} className="mx-auto text-content-quaternary mb-2" />
            <p className="text-xs text-content-secondary">
              {t('costs.empty_pick_region_above', {
                defaultValue:
                  'Pick a region card above and click Install to load a regional cost database.',
              })}
            </p>
          </div>
        )}

        {/* Per-region table — only when at least one region is installed */}
        {hasData && (
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
              {regionStats!.map((rs) => {
                const db = CWICR_DATABASES.find((d) => d.id === rs.region);
                const isActive = activeDbId === rs.region;
                const isDeleting = deletingRegion === rs.region;
                // Fallback labels for non-CWICR regions
                const regionLabel = db?.name ?? (rs.region === 'CUSTOM' ? 'My Database' : rs.region === 'DACH' ? 'DACH Region' : rs.region);
                // Pass either the curated flagId or the raw region key —
                // CountryFlag's resolveIso handles both shapes (DE_BERLIN
                // -> de via prefix split, USA_USD -> us via the
                // non-ISO-prefix map). Falling back to a Globe icon when
                // it can't resolve, never to "first 2 letters of city".
                const flagCode = db?.flagId ?? (rs.region === 'DACH' ? 'de' : rs.region);
                return (
                  <tr key={rs.region} className="hover:bg-surface-secondary/50 transition-colors">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-5 w-8 items-center justify-center">
                          <CountryFlag code={flagCode} size={32} className="shadow-xs border border-black/5" />
                          <Globe size={14} className="text-content-tertiary hidden [&:only-child]:block" />
                        </span>
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
                          onClick={async () => {
                            const ok = await confirm({
                              title: t('costs.confirm_delete_region_title', {
                                defaultValue: 'Delete region cost items?',
                              }),
                              message: t('costs.confirm_delete_region', {
                                defaultValue: 'Delete all cost items for {{region}}? This cannot be undone.',
                                region: db?.name ?? rs.region,
                              }),
                              confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                              variant: 'danger',
                            });
                            if (!ok) return;
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
        )}

        {/* Clear all confirmation */}
        {showClearConfirm && hasData && (
          <div className="mt-4 rounded-xl border border-semantic-error/20 bg-semantic-error-bg/30 p-4">
            <p className="text-sm font-medium text-semantic-error mb-1">
              {t('costs.clear_all_confirm_title', {
                defaultValue: 'Clear all {{count}} databases?',
                count: regionCount,
              })}
            </p>
            <p className="text-xs text-content-secondary mb-3">
              {t('costs.clear_all_confirm_body', {
                defaultValue:
                  'This will permanently remove all {{count}} CWICR cost items. You can re-import them later.',
                count: totalItems,
              })}
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
      <ConfirmDialog {...confirmProps} />
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
  // Elapsed-time tick so the progress panel can show a phased bar instead
  // of a bare spinner. Local generation runs sentence-transformers and
  // takes 30–60 s on a cold model — no backend event stream to hook
  // into, so we estimate progress from time-since-click (same pattern
  // as the CWICR cost-DB loader above).
  const [vectorElapsed, setVectorElapsed] = useState(0);
  useEffect(() => {
    if (!loadingRegion && !isIndexingAll) {
      setVectorElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(
      () => setVectorElapsed(Math.floor((Date.now() - start) / 1000)),
      500,
    );
    return () => clearInterval(interval);
  }, [loadingRegion, isIndexingAll]);

  // Check vector DB status (LanceDB embedded or Qdrant)
  const { data: vectorStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['costs', 'vector', 'status'],
    queryFn: () => apiGet<VectorStatus>('/v1/costs/vector/status/'),
    retry: false,
    refetchInterval: (loadingRegion || isIndexingAll) ? 5000 : false,
  });

  const isConnected = vectorStatus?.connected ?? false;

  // Per-region vector counts — only fetch when vector DB is connected
  const { data: vectorRegionStats, refetch: refetchVectorRegions } = useQuery({
    queryKey: ['costs', 'vector', 'regions'],
    queryFn: () => apiGet<VectorRegionStat[]>('/v1/costs/vector/regions/').catch(() => [] as VectorRegionStat[]),
    retry: false,
    enabled: isConnected,
  });

  // Region stats for cost item counts
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/'),
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
            if (import.meta.env.DEV) console.error('GitHub vector load failed, falling back to local generation:', err);
            // GitHub vectors not available — generate locally for this region
            const token = useAuthStore.getState().accessToken;
            const res = await fetch(`/api/v1/costs/vector/index/?region=${encodeURIComponent(db.id)}`, {
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
      const res = await fetch('/api/v1/costs/vector/index/', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setLastResult({ region: 'all', indexed: data.indexed, duration: data.duration_seconds });
        addToast({
          type: 'success',
          title: t('costs.vector_index_created', { defaultValue: 'Vector index created' }),
          message: `${data.indexed.toLocaleString()} items indexed in ${data.duration_seconds}s`,
        });
        refetchStatus();
        refetchVectorRegions();
        queryClient.invalidateQueries({ queryKey: ['costs', 'vector'] });
      } else {
        const err = await res.json().catch(() => ({ detail: 'Indexing failed' }));
        addToast({ type: 'error', title: t('costs.indexing_failed', { defaultValue: 'Indexing failed' }), message: extractErrorMessageFromBody(err) ?? 'Indexing failed' });
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
                CWICR Vector Database - AI Semantic Search
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
          search - find cost items by meaning, not just keywords. E.g. &quot;concrete wall&quot; finds
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
                <strong className="text-content-secondary">Option A - Qdrant (best quality, 3072d):</strong><br/>
                <code className="text-2xs bg-surface-secondary px-1 py-0.5 rounded">docker run -p 6333:6333 qdrant/qdrant</code>
              </div>
              <div>
                <strong className="text-content-secondary">Option B - LanceDB (lightweight, 384d):</strong><br/>
                <code className="text-2xs bg-surface-secondary px-1 py-0.5 rounded">pip install lancedb sentence-transformers</code>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Region grid — same style as CWICR */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5 mb-5">
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

            {/* ── Phased vector-load progress panel ────────────────
                Mirrors the CWICR cost-DB progress panel above so
                users aren't staring at a lone spinner for the full
                30-60 s embedding generation. Phases are elapsed-time
                estimates — the backend runs synchronously and has no
                SSE channel to report real progress. */}
            {isLoading && (() => {
              const loadingDb = loadingRegion
                ? CWICR_DATABASES.find((d) => d.id === loadingRegion)
                : null;
              // Four phases roughly match the backend sequence in
              // ``load_vector_from_github``:
              //   0-3 s  : HEAD / download attempt from GitHub
              //   3-15 s : sentence-transformers model load (first run)
              //  15-45 s : batched embedding generation
              //   45+ s  : indexing into LanceDB + region stats refresh
              const phase =
                vectorElapsed < 3 ? 0 : vectorElapsed < 15 ? 1 : vectorElapsed < 45 ? 2 : 3;
              const phaseLabels = [
                t('costs.vec_phase_checking', {
                  defaultValue: 'Checking pre-built vectors on GitHub...',
                }),
                t('costs.vec_phase_model', {
                  defaultValue: 'Loading embedding model (first-time only)...',
                }),
                t('costs.vec_phase_embedding', {
                  defaultValue: 'Generating 384d embeddings from cost items...',
                }),
                t('costs.vec_phase_indexing', {
                  defaultValue: 'Indexing into LanceDB and refreshing stats...',
                }),
              ];
              // Never reach 100% on the estimate — only the success
              // toast flips the bar to done. Asymptote towards 95.
              const progressPct = Math.min(
                95,
                phase === 0
                  ? vectorElapsed * 6
                  : phase === 1
                    ? 18 + (vectorElapsed - 3) * 2
                    : phase === 2
                      ? 42 + (vectorElapsed - 15) * 1.2
                      : 78 + Math.min(17, (vectorElapsed - 45) * 0.4),
              );
              return (
                <div className="mb-4 rounded-xl border border-purple-300/40 bg-purple-50/30 dark:bg-purple-500/5 overflow-hidden">
                  <div className="px-4 pt-3 pb-3">
                    <div className="flex items-center gap-2.5 mb-2.5">
                      <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 text-white">
                        <Sparkles size={16} />
                        <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-purple-400 animate-ping" />
                        <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-purple-500" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-semibold text-content-primary truncate">
                            {isIndexingAll
                              ? t('costs.vec_indexing_all', {
                                  defaultValue: 'Generating vectors for all regions...',
                                })
                              : t('costs.vec_indexing_region', {
                                  defaultValue: 'Generating vectors for {{name}}...',
                                  name: loadingDb?.name ?? 'database',
                                })}
                          </h4>
                          <span className="text-xs text-purple-600 font-mono tabular-nums shrink-0">
                            {Math.floor(vectorElapsed / 60)}:{String(vectorElapsed % 60).padStart(2, '0')}
                          </span>
                        </div>
                        <p className="text-2xs text-content-tertiary mt-0.5 truncate">
                          {phaseLabels[phase]}
                        </p>
                      </div>
                    </div>

                    {/* Progress bar */}
                    <div className="mb-1.5">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-2xs font-medium text-content-secondary">
                          {t('costs.vec_phase_progress', {
                            defaultValue: 'Step {{step}} of 4',
                            step: phase + 1,
                          })}
                        </span>
                        <span className="text-2xs font-semibold text-purple-600 tabular-nums">
                          {Math.round(progressPct)}%
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
                        <div
                          className="h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r from-purple-500 via-blue-500 to-purple-500 bg-[length:200%_100%] animate-shimmer"
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>

                    {/* Phase dots */}
                    <div className="flex items-center gap-1 text-2xs">
                      {[
                        t('costs.vec_step_fetch', { defaultValue: 'Fetch' }),
                        t('costs.vec_step_model', { defaultValue: 'Model' }),
                        t('costs.vec_step_embed', { defaultValue: 'Embed' }),
                        t('costs.vec_step_index', { defaultValue: 'Index' }),
                      ].map((label, i) => (
                        <div key={label} className="flex items-center gap-1">
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              i < phase
                                ? 'bg-semantic-success'
                                : i === phase
                                  ? 'bg-purple-500 animate-pulse'
                                  : 'bg-surface-tertiary'
                            }`}
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
                          {i < 3 && (
                            <span className="text-content-quaternary mx-0.5">&middot;</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* Last result */}
            {lastResult && !isLoading && (
              <div className="rounded-lg bg-semantic-success-bg/40 border border-semantic-success/20 px-4 py-3 mb-4">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={14} className="text-semantic-success" />
                  <span className="text-xs font-medium text-semantic-success">
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

// ── Column Mapping Panel ─────────────────────────────────────────────────────

type CatalogTargetMode = 'new' | 'existing';

interface ColumnMappingPanelProps {
  data: PreviewResult;
  columnMap: Record<string, string>;
  onChangeField: (field: string, header: string) => void;
  catalogMode: CatalogTargetMode;
  onCatalogModeChange: (mode: CatalogTargetMode) => void;
  catalogName: string;
  onCatalogNameChange: (value: string) => void;
  catalogCurrency: string;
  onCatalogCurrencyChange: (value: string) => void;
  existingCatalogId: string;
  onExistingCatalogChange: (id: string) => void;
  /** User catalogs for the "existing catalog" dropdown. */
  catalogs: CostCatalog[];
  onImport: () => void;
  onCancel: () => void;
  importing: boolean;
}

function ColumnMappingPanel({
  data,
  columnMap,
  onChangeField,
  catalogMode,
  onCatalogModeChange,
  catalogName,
  onCatalogNameChange,
  catalogCurrency,
  onCatalogCurrencyChange,
  existingCatalogId,
  onExistingCatalogChange,
  catalogs,
  onImport,
  onCancel,
  importing,
}: ColumnMappingPanelProps) {
  const { t } = useTranslation();
  const fieldMeta = useTargetFieldMeta();

  const requiredFields = data.required_fields.length > 0 ? data.required_fields : ['description'];
  const isRequired = (field: string) => requiredFields.includes(field);

  // All required fields must be mapped before import is allowed.
  const unmappedRequired = requiredFields.filter((f) => !columnMap[f]);

  // Currency presence tracks the LIVE mapping (the seeded map mirrors the
  // preview's auto-detection, and the user may map / unmap the column
  // here). When the file carries no mapped currency column, a NEW catalog
  // needs an explicit currency - same rule the backend enforces with 422.
  const hasCurrencyColumn = Boolean(columnMap['currency']);
  const newCatalogCurrencyMissing =
    catalogMode === 'new' && !hasCurrencyColumn && !catalogCurrency;
  const catalogTargetValid =
    catalogMode === 'existing'
      ? Boolean(existingCatalogId)
      : Boolean(catalogName.trim()) && !newCatalogCurrencyMissing;

  const canImport = unmappedRequired.length === 0 && catalogTargetValid && !importing;
  const selectedExisting = catalogs.find((c) => c.id === existingCatalogId);

  const modeOptionClass = (active: boolean) =>
    `flex items-start gap-2.5 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
      active
        ? 'border-oe-blue/50 bg-oe-blue-subtle/15'
        : 'border-border-light hover:bg-surface-secondary/50'
    }`;

  // Show up to 3 sample rows under their headers.
  const sampleRows = data.sample_rows.slice(0, 3);

  // Selectable header options: drop empty-string headers (they would collide
  // with the not-mapped sentinel). Duplicate header names share the same
  // option VALUE, so the select cannot tell them apart - picking the second
  // occurrence would silently map the first. Keep only the FIRST occurrence
  // of each name (the one the backend's column_map resolves to anyway) and
  // surface a warning line under the mapping panel.
  const headerOptions: Array<{ header: string; index: number }> = [];
  const duplicateHeaders: string[] = [];
  const seenHeaders = new Set<string>();
  data.headers.forEach((header, index) => {
    if (header.trim() === '') return;
    if (seenHeaders.has(header)) {
      if (!duplicateHeaders.includes(header)) duplicateHeaders.push(header);
      return;
    }
    seenHeaders.add(header);
    headerOptions.push({ header, index });
  });

  return (
    <Card className="animate-card-in" padding="none">
      <div className="px-6 pt-5 pb-4">
        <div className="flex items-start gap-3 mb-1">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
            <FileSpreadsheet size={18} className="text-oe-blue" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs_import.map_columns_title', { defaultValue: 'Map your columns' })}
            </h3>
            <p className="text-xs text-content-tertiary mt-0.5">
              {t('costs_import.map_columns_subtitle', {
                defaultValue:
                  'Tell us which column in your file holds each value. We pre-filled the ones we recognised.',
              })}
            </p>
          </div>
        </div>
      </div>

      {/* Mapping rows */}
      <div className="px-6 pb-2">
        <div className="rounded-xl border border-border-light divide-y divide-border-light overflow-hidden">
          {data.target_fields.map((field) => {
            const meta = fieldMeta(field);
            const required = isRequired(field);
            const value = columnMap[field] ?? NOT_MAPPED;
            const missing = required && !value;
            return (
              <div
                key={field}
                className={`flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4 ${
                  missing ? 'bg-semantic-error-bg/20' : ''
                }`}
              >
                <div className="sm:w-1/3">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-content-primary">{meta.label}</span>
                    {required && (
                      <Badge variant="neutral" size="sm" className="text-2xs px-1.5 py-0">
                        {t('costs_import.required', { defaultValue: 'required' })}
                      </Badge>
                    )}
                  </div>
                  {meta.hint && (
                    <p className="text-2xs text-content-tertiary mt-0.5">{meta.hint}</p>
                  )}
                </div>
                <div className="flex-1">
                  <select
                    value={value}
                    onChange={(e) => onChangeField(field, e.target.value)}
                    aria-label={meta.label}
                    className={`w-full rounded-lg border bg-surface-elevated px-3 py-2 text-sm text-content-primary focus:outline-none focus:border-oe-blue/50 transition-colors ${
                      missing ? 'border-semantic-error/50' : 'border-border-light'
                    }`}
                  >
                    <option value={NOT_MAPPED}>
                      {t('costs_import.not_mapped', { defaultValue: 'Not mapped' })}
                    </option>
                    {headerOptions.map(({ header, index }) => (
                      <option key={`opt-${index}`} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                  {missing && (
                    <p className="text-2xs text-semantic-error mt-1">
                      {t('costs_import.field_required_hint', {
                        defaultValue: 'Map a column for this field to continue.',
                      })}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {duplicateHeaders.length > 0 && (
          <div className="mt-2 space-y-0.5">
            {duplicateHeaders.map((name) => (
              <p key={name} className="text-2xs text-amber-700 dark:text-amber-400">
                {t('costs_import.duplicate_header', {
                  defaultValue:
                    'Duplicate column name "{{name}}" - only the first occurrence is used.',
                  name,
                })}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Sample preview table */}
      {sampleRows.length > 0 && (
        <div className="px-6 pt-3 pb-2">
          <p className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
            {t('costs_import.sample_preview', { defaultValue: 'Sample from your file' })}
          </p>
          <div className="rounded-xl border border-border-light overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-surface-tertiary text-left">
                  {data.headers.map((header, ci) => (
                    <th
                      key={`head-${ci}`}
                      className="px-3 py-2 font-medium text-content-secondary whitespace-nowrap"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {sampleRows.map((row, ri) => (
                  <tr key={`sample-${ri}`} className="hover:bg-surface-secondary/40">
                    {data.headers.map((header, ci) => (
                      <td
                        key={`${header}-${ci}`}
                        className="px-3 py-2 text-content-secondary whitespace-nowrap max-w-[18rem] truncate"
                      >
                        {row[ci] ?? ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Target catalog step - the imported rows always land in a user
          catalog: a new one created inline, or an existing one. */}
      <div className="px-6 pt-3 pb-2">
        <p className="text-sm font-medium text-content-primary mb-1">
          {t('costs_catalogs.import_target_title', { defaultValue: 'Where should these items go?' })}
        </p>
        <p className="text-2xs text-content-tertiary mb-2">
          {t('costs_catalogs.import_target_hint', {
            defaultValue: 'Items are grouped into a catalog so you can manage and export them later.',
          })}
        </p>

        <div className="grid gap-2 sm:grid-cols-2 max-w-2xl">
          {/* New catalog */}
          <label className={modeOptionClass(catalogMode === 'new')}>
            <input
              type="radio"
              name="catalog-target-mode"
              checked={catalogMode === 'new'}
              onChange={() => onCatalogModeChange('new')}
              className="mt-0.5"
            />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-content-primary">
                {t('costs_catalogs.import_new_catalog', { defaultValue: 'Create a new catalog' })}
              </span>
              {catalogMode === 'new' && (
                <span className="block mt-2 space-y-2">
                  <input
                    id="catalog-name"
                    type="text"
                    value={catalogName}
                    onChange={(e) => onCatalogNameChange(e.target.value)}
                    placeholder={t('costs_import.catalog_name_placeholder', {
                      defaultValue: 'e.g. My price book 2026',
                    })}
                    aria-label={t('costs_import.catalog_name', { defaultValue: 'Catalog name' })}
                    className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:border-oe-blue/50 transition-colors"
                  />
                  <select
                    value={catalogCurrency}
                    onChange={(e) => onCatalogCurrencyChange(e.target.value)}
                    aria-label={t('costs_catalogs.currency_label', { defaultValue: 'Currency' })}
                    className={`w-full rounded-lg border bg-surface-elevated px-3 py-2 text-sm text-content-primary focus:outline-none focus:border-oe-blue/50 transition-colors ${
                      newCatalogCurrencyMissing
                        ? 'border-semantic-error/60 ring-1 ring-semantic-error/30'
                        : 'border-border-light'
                    }`}
                  >
                    <option value="">
                      {t('costs_catalogs.import_currency_select', { defaultValue: 'Select currency...' })}
                    </option>
                    {COMMON_CURRENCIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                  {newCatalogCurrencyMissing ? (
                    <span className="block text-2xs text-semantic-error">
                      {t('costs_catalogs.import_currency_required', {
                        defaultValue:
                          'The file has no currency column, so the new catalog needs an explicit currency.',
                      })}
                    </span>
                  ) : (
                    <span className="block text-2xs text-content-tertiary">
                      {hasCurrencyColumn
                        ? t('costs_catalogs.import_currency_detected', {
                            defaultValue:
                              'Currency column detected. Leave empty to derive the catalog currency from the file.',
                          })
                        : t('costs_catalogs.currency_hint', {
                            defaultValue: 'Items without their own currency inherit this code.',
                          })}
                    </span>
                  )}
                </span>
              )}
            </span>
          </label>

          {/* Existing catalog */}
          <label className={modeOptionClass(catalogMode === 'existing')}>
            <input
              type="radio"
              name="catalog-target-mode"
              checked={catalogMode === 'existing'}
              onChange={() => onCatalogModeChange('existing')}
              className="mt-0.5"
            />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-content-primary">
                {t('costs_catalogs.import_existing_catalog', { defaultValue: 'Add to an existing catalog' })}
              </span>
              {catalogMode === 'existing' && (
                <span className="block mt-2 space-y-1.5">
                  {catalogs.length === 0 ? (
                    <span className="block text-2xs text-content-tertiary">
                      {t('costs_catalogs.import_existing_empty', {
                        defaultValue: 'No catalogs yet. Create a new one instead.',
                      })}
                    </span>
                  ) : (
                    <>
                      <select
                        value={existingCatalogId}
                        onChange={(e) => onExistingCatalogChange(e.target.value)}
                        aria-label={t('costs_catalogs.import_existing_catalog', { defaultValue: 'Add to an existing catalog' })}
                        className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm text-content-primary focus:outline-none focus:border-oe-blue/50 transition-colors"
                      >
                        <option value="">
                          {t('costs_catalogs.import_existing_select', { defaultValue: 'Select a catalog...' })}
                        </option>
                        {catalogs.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name} ({c.currency}, {c.item_count})
                          </option>
                        ))}
                      </select>
                      {selectedExisting && (
                        <span className="block text-2xs text-content-tertiary">
                          {t('costs_catalogs.import_into_named', {
                            defaultValue: 'Items will be imported into "{{name}}" ({{currency}}).',
                            name: selectedExisting.name,
                            currency: selectedExisting.currency,
                          })}
                        </span>
                      )}
                    </>
                  )}
                </span>
              )}
            </span>
          </label>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light mt-2">
        {/* Inline blocker message - explains exactly why Import is disabled
            instead of leaving a dead button. */}
        {unmappedRequired.length > 0 && (
          <span className="mr-auto inline-flex items-center gap-1.5 text-xs text-semantic-error">
            <AlertTriangle size={13} className="shrink-0" />
            {t('costs_catalogs.import_required_missing', {
              defaultValue: 'Map the required columns before importing: {{fields}}.',
              fields: unmappedRequired.map((f) => fieldMeta(f).label).join(', '),
            })}
          </span>
        )}
        {/* This action discards the staged file entirely (handleReset), so it
            is labelled Cancel rather than Back. */}
        <Button variant="secondary" onClick={onCancel} disabled={importing}>
          {t('costs_import.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={onImport}
          disabled={!canImport}
          loading={importing}
          icon={
            importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />
          }
        >
          {importing
            ? t('costs.import_importing', { defaultValue: 'Importing...' })
            : t('costs_import.import_mapped', { defaultValue: 'Import' })}
        </Button>
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

  // Column-mapping panel state. Once a file is previewed we move into the
  // mapping step: `previewData` holds the headers/sample/suggestions,
  // `columnMap` is the user-editable canonical-field -> raw-header mapping and
  // `catalogName` groups the imported rows.
  const [previewData, setPreviewData] = useState<PreviewResult | null>(null);
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [catalogName, setCatalogName] = useState('');
  // Target catalog step: create a new catalog inline (name + currency) or
  // import into an existing one. New is the default - the name is seeded
  // from the file name, so the zero-decision path keeps working.
  const [catalogMode, setCatalogMode] = useState<'new' | 'existing'>('new');
  const [catalogCurrency, setCatalogCurrency] = useState('');
  const [existingCatalogId, setExistingCatalogId] = useState('');

  // User catalogs for the "existing catalog" dropdown - only needed once
  // the mapping panel is on screen.
  const { data: userCatalogs } = useQuery<CostCatalog[]>({
    queryKey: ['costs', 'catalogs'],
    queryFn: fetchCostCatalogs,
    retry: false,
    staleTime: 60_000,
    enabled: previewData !== null,
  });

  // Strip the extension from a filename for a friendly default catalog name.
  const baseName = useCallback(
    (name: string) => name.replace(/\.[^.]+$/, '').trim() || name,
    [],
  );

  // The file currently staged by the user. Preview results arriving for any
  // other (stale) file are ignored, so a slow preview response can never
  // clobber the mapping panel of a file picked later.
  const currentFileRef = useRef<File | null>(null);

  // Preview step - kicked off after a file is chosen. On success we enter the
  // mapping panel; on failure the file stays staged and the user can run the
  // auto-detect "Import All" fallback that renders below the drop zone.
  const previewMutation = useMutation({
    mutationFn: (file: File) => previewCostFile(file),
    onSuccess: (data, file) => {
      // Stale response for a file that is no longer staged - ignore it.
      if (currentFileRef.current !== file) return;
      setPreviewData(data);
      // Seed the editable map from the backend's suggestions, but only keep
      // suggestions whose header actually exists in the file.
      const seeded: Record<string, string> = {};
      for (const field of data.target_fields) {
        const suggested = data.suggested_map[field];
        seeded[field] = suggested && data.headers.includes(suggested) ? suggested : NOT_MAPPED;
      }
      setColumnMap(seeded);
      setCatalogName(baseName(file.name));
    },
    onError: (err: Error, file) => {
      if (currentFileRef.current !== file) return;
      // Preview unavailable (network / parse). Keep the staged file and let
      // the user decide: the "Import All" fallback button below the drop zone
      // runs the auto-detect import. Never import without an explicit click.
      addToast({
        type: 'warning',
        title: t('costs_import.preview_failed', { defaultValue: 'Could not preview columns' }),
        message: t('costs_import.preview_failed_fallback', {
          defaultValue:
            'Your file is still staged. Use "Import All" below to import it with automatic column detection.',
        }),
      });
      if (import.meta.env.DEV) console.error('Cost-file preview failed:', err);
    },
  });

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

      currentFileRef.current = file;
      setSelectedFile(file);
      setPreview({
        name: file.name,
        size: formatFileSize(file.size),
        type,
      });
      setResult(null);
      setPreviewData(null);
      setColumnMap({});
      setCatalogMode('new');
      setCatalogCurrency('');
      setExistingCatalogId('');
      previewMutation.mutate(file);
    },
    // The mutation RESULT object is a new reference every render; only the
    // ``mutate`` function is stable (react-query guarantees it), so depend
    // on that to keep handleFile from being re-created each render.
    [addToast, t, previewMutation.mutate],
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

  // Shared success/error handling for both the mapped import and the
  // auto-detect fallback.
  const onImportSuccess = useCallback(
    (data: ImportResult) => {
      setResult(data);
      setPreviewData(null);
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      if (data.imported > 0) {
        addToast({
          type: 'success',
          title: t('costs.import_success', { defaultValue: 'Import complete' }),
          message: data.catalog
            ? t('costs_import.import_success_catalog', {
                defaultValue: '{{count}} items imported into "{{catalog}}".',
                count: data.imported,
                catalog: data.catalog,
              })
            : t('costs_import.import_success_count', {
                defaultValue: '{{count}} items imported successfully.',
                count: data.imported,
              }),
        });
      }
      // Mixed-currency rows are imported as-is (never silently rewritten) -
      // surface a separate non-blocking warning so the user knows some rows
      // kept a currency different from the catalog currency.
      if ((data.mixed_currency_count ?? 0) > 0) {
        addToast({
          type: 'warning',
          title: t('costs_catalogs.mixed_currency_label', { defaultValue: 'Mixed currencies' }),
          message: t('costs_catalogs.mixed_currency_warning', {
            defaultValue:
              '{{count}} rows carry a currency different from the catalog currency {{currency}}. They were imported with their own currency, no conversion applied.',
            count: data.mixed_currency_count,
            currency: data.catalog_currency ?? '',
          }),
        });
      }
    },
    [addToast, queryClient, t],
  );

  const onImportError = useCallback(
    (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.import_failed', { defaultValue: 'Import failed' }),
        message: err.message,
      });
    },
    [addToast, t],
  );

  // Primary import - uses the user's chosen column map + target catalog
  // (existing catalog id, or new-catalog name + currency).
  const importMutation = useMutation({
    mutationFn: () => {
      if (!selectedFile) throw new Error('No file selected');
      // Drop unmapped (empty) fields so the backend only receives real columns.
      const cleanMap: Record<string, string> = {};
      for (const [field, header] of Object.entries(columnMap)) {
        if (header) cleanMap[field] = header;
      }
      return uploadCostFile(selectedFile, {
        columnMap: cleanMap,
        ...(catalogMode === 'existing'
          ? { catalogId: existingCatalogId }
          : { catalogName, catalogCurrency }),
      });
    },
    onSuccess: onImportSuccess,
    onError: onImportError,
  });

  // Fallback import - no column map, backend auto-detects. Triggered only by
  // the explicit "Import All" button so the user is never hard-blocked.
  const directImportMutation = useMutation({
    mutationFn: (file: File) => uploadCostFile(file),
    onSuccess: onImportSuccess,
    onError: onImportError,
  });

  const handleReset = useCallback(() => {
    currentFileRef.current = null;
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
    setPreviewData(null);
    setColumnMap({});
    setCatalogName('');
    setCatalogMode('new');
    setCatalogCurrency('');
    setExistingCatalogId('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('costs.title', 'Cost Database'), to: '/costs' },
          { label: t('costs.import_title', 'Import Cost Database') },
        ]}
      />

      {/* Canonical top block — the breadcrumb above carries the Cost Database
          > Import trail; the module name + icon are shown by the global top
          bar. The page renders only its subtitle. */}
      <PageHeader
        srTitle={t('costs.import_title', { defaultValue: 'Import Cost Database' })}
        subtitle={t('costs.import_subtitle', {
          defaultValue: 'Load a pricing database or upload your own file.',
        })}
      />

      <DismissibleInfo
        storageKey="costs-import"
        title={t('costs_import.intro_title', { defaultValue: 'Get a regional price book in minutes' })}
        more={t('costs_import.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('costs_import.intro_more')} /> : undefined}
        links={[
          { label: t('nav.costs', { defaultValue: 'Cost Database' }), onClick: () => navigate('/costs') },
          { label: t('nav.catalog', { defaultValue: 'Resource Catalog' }), onClick: () => navigate('/catalog') },
          { label: t('nav.assemblies', { defaultValue: 'Assemblies' }), onClick: () => navigate('/assemblies') },
        ]}
      >
        {t('costs_import.intro_body', {
          defaultValue:
            'Install a regional CWICR cost database by country and currency, or upload your own Parquet file, with full resource and cost breakdowns indexed for offline use. Once installed the rates appear in the cost database and become matchable across catalog, assemblies and BOQ.',
        })}
      </DismissibleInfo>

      {/* DDC CWICR Database -- 11 regional databases */}
      <Card padding="none">
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
                55,719 items per region &middot; 85 fields &middot; 48 databases &middot; by
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
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-border-light" />
        <span className="text-xs font-medium text-content-tertiary uppercase tracking-wider">
          {t('costs.or_upload_own', { defaultValue: 'or upload your own file' })}
        </span>
        <div className="h-px flex-1 bg-border-light" />
      </div>

      {/* Import result summary */}
      {result && (
        <Card className="animate-card-in">
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
                <div className="text-2xl font-bold text-semantic-success">{result.imported}</div>
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

            {/* Target catalog summary */}
            {result.catalog && (
              <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 text-xs text-content-secondary">
                <BookOpen size={14} className="text-oe-blue shrink-0" />
                {t('costs_catalogs.result_catalog_line', {
                  defaultValue: 'Imported into catalog "{{name}}"{{currency}}.',
                  name: result.catalog,
                  currency: result.catalog_currency ? ` (${result.catalog_currency})` : '',
                })}
              </div>
            )}

            {/* Mixed-currency warning - rows kept their own currency */}
            {(result.mixed_currency_count ?? 0) > 0 && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-500/40 dark:bg-amber-900/20 dark:text-amber-200">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span>
                  <span className="font-semibold block mb-0.5">
                    {t('costs_catalogs.mixed_currency_label', { defaultValue: 'Mixed currencies' })}
                  </span>
                  {t('costs_catalogs.mixed_currency_warning', {
                    defaultValue:
                      '{{count}} rows carry a currency different from the catalog currency {{currency}}. They were imported with their own currency, no conversion applied.',
                    count: result.mixed_currency_count,
                    currency: result.catalog_currency ?? '',
                  })}
                </span>
              </div>
            )}

            {/* Error details (first 5) */}
            {result.errors.length > 0 && (
              <div className="rounded-lg border border-semantic-error/20 bg-semantic-error-bg/30 p-3">
                <p className="text-xs font-medium text-semantic-error mb-2">
                  {t('costs.import_error_details', { defaultValue: 'Error details' })}
                </p>
                <div className="space-y-1.5">
                  {result.errors.slice(0, 5).map((err) => (
                    <p key={`row-${err.row}`} className="text-xs text-content-secondary">
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
        <div className="space-y-5">
          {/* Supported formats */}
          <Card>
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
                    <FileSpreadsheet size={14} className="text-semantic-success shrink-0" />
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
                      'Columns are auto-detected. Accepted headers: Code, Description, Unit, Rate/Price/Cost, Currency, Classification.',
                  })}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs font-medium text-content-secondary mr-1">
                    {t('costs.import_templates_label', { defaultValue: 'Download a template:' })}
                  </span>
                  <a
                    href="/templates/cost_database_template.csv"
                    download
                    className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                  >
                    <Download size={12} />
                    {t('costs.import_template_minimal', { defaultValue: 'Minimal CSV (3 rows)' })}
                  </a>
                  <a
                    href="/templates/example_us_construction.csv"
                    download
                    className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                  >
                    <Download size={12} />
                    {t('costs.import_template_example', { defaultValue: 'Example US construction (30 rows)' })}
                  </a>
                  <a
                    href="/templates/cost_database_with_assemblies.json"
                    download
                    className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                  >
                    <Download size={12} />
                    {t('costs.import_template_recipes', { defaultValue: 'Recipes JSON (6 assemblies)' })}
                  </a>
                </div>
                <p className="mt-2 text-[11px] text-content-tertiary">
                  {t('costs.import_template_help', {
                    defaultValue: 'See docs/cost-database-import.md for the full resource-based costing guide.',
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
                        defaultValue: 'Excel (.xlsx) or CSV (.csv)',
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Previewing columns - brief loading state before the mapping panel */}
          {selectedFile && previewMutation.isPending && (
            <div className="flex items-center justify-center gap-2 rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-6 text-sm text-content-secondary animate-fade-in">
              <Loader2 size={16} className="animate-spin text-oe-blue" />
              {t('costs_import.analyzing_columns', {
                defaultValue: 'Reading columns from your file...',
              })}
            </div>
          )}

          {/* Column mapping panel - shown once preview resolves */}
          {selectedFile && previewData && (
            <ColumnMappingPanel
              data={previewData}
              columnMap={columnMap}
              onChangeField={(field, header) =>
                setColumnMap((prev) => ({ ...prev, [field]: header }))
              }
              catalogMode={catalogMode}
              onCatalogModeChange={setCatalogMode}
              catalogName={catalogName}
              onCatalogNameChange={setCatalogName}
              catalogCurrency={catalogCurrency}
              onCatalogCurrencyChange={setCatalogCurrency}
              existingCatalogId={existingCatalogId}
              onExistingCatalogChange={setExistingCatalogId}
              catalogs={userCatalogs ?? []}
              onImport={() => importMutation.mutate()}
              onCancel={handleReset}
              importing={importMutation.isPending}
            />
          )}

          {/* Fallback actions - only when a file is staged but there is no
              preview yet and we are not actively previewing (e.g. preview
              failed or produced nothing). Keeps a direct, user-initiated
              auto-detect import path available. */}
          {selectedFile && !previewData && !previewMutation.isPending && (
            <div className="flex items-center justify-end gap-3 animate-fade-in">
              <Button variant="secondary" onClick={handleReset} disabled={directImportMutation.isPending}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => directImportMutation.mutate(selectedFile)}
                loading={directImportMutation.isPending}
                icon={
                  directImportMutation.isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Upload size={16} />
                  )
                }
              >
                {directImportMutation.isPending
                  ? t('costs.import_importing', { defaultValue: 'Importing...' })
                  : t('costs.import_all', { defaultValue: 'Import All' })}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
