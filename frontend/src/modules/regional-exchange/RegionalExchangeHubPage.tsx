// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The world exchange hub: pick a market, pick its format, move the file.
 *
 * What this replaced
 * ------------------
 *
 * This page used to be twenty labelled cards that navigated away, and it
 * existed because issue #217 had ruled out twenty sidebar rows and the BOQ
 * link meant to replace them was never written, leaving every country route
 * reachable only by typing its URL. The module it belongs to also shipped
 * disabled by default, so for most installations the whole thing was off
 * and invisible at the same time.
 *
 * It is now the module's front door and has a sidebar row of its own beside
 * the BOQ, which is what a person looking for "how do I get my tender file
 * in" actually goes looking for.
 *
 * Why the list comes from the backend
 * -----------------------------------
 *
 * Every row says whether we can read and write that market's document. The
 * honest answer changes when an importer is added or removed, so the answer
 * is computed in Python from the importer and exporter registries and sent
 * here. Nothing on this page decides what we support. That matters more
 * than it sounds: the failure mode of a hand-written capability list is a
 * user sending a file we cannot read, on the strength of a green tick we
 * wrote once and never revisited.
 *
 * Three words, not two
 * --------------------
 *
 * A format is `native`, `assisted` or `none`, and the middle one earns its
 * place. `assisted` means we have no reader but the guided import can open
 * the file, propose a mapping and let a person confirm every row. Calling
 * that "supported" would oversell it and calling it "unsupported" would
 * send someone away who could have got their data in this afternoon.
 *
 * The market is a preselection, never a filter
 * --------------------------------------------
 *
 * Choosing a flag moves the highlight and changes which format is offered
 * first. It never removes a format from the page, because the ordinary
 * reason to open this screen is that somebody sent you a file from a
 * market that is not yours.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Check, Download, Loader2, Search, Upload } from 'lucide-react';
import { Badge, Button, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { CountryFlag, hasFlagArt } from '@/shared/ui/CountryFlag';
import { apiGet, downloadWithAuth, getAuthToken } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { regionDisplayName } from '@/features/cases/regions';
import { COUNTRY_TEMPLATES } from './regionalRegistry';
import {
  IMPORT_ENDPOINT,
  exportEndpoint,
  formatsForMarket,
  inferMarket,
  marketsIn,
  specialistPageFor,
  useExchangeCatalogue,
  type ExchangeFormatInfo,
  type SupportLevel,
} from './exchangeCatalogue';

interface Project {
  id: string;
  name: string;
  /** ISO 3166-1 alpha-2, set on the project. Absent on older projects. */
  country_code?: string | null;
  /** Catalogue region key, which may carry a country and a city. */
  region?: string | null;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
}

interface ImportOutcome {
  imported: number | null;
  skipped: number;
  detectedFormat: string;
  method: string;
  errors: string[];
}

/* ── Small pieces ──────────────────────────────────────────────────── */

/** A flag, or the country's code when we carry no artwork for it.
 *
 *  Never nothing. `CountryFlag` renders null for a code it has no drawing
 *  for, which on a row whose whole job is to say which country it belongs
 *  to reads as a broken card. The two letters are less pretty and always
 *  legible, and they are also what the reader would have to fall back on
 *  anyway.
 *
 *  The lookup is the strict one on purpose. `CountryFlag` also accepts
 *  cost-database region keys and language prefixes, under which `AR` means
 *  Arabic and resolves to the United Arab Emirates; here `AR` is Argentina
 *  and being answered with the wrong country's flag would be worse than
 *  being answered with none. */
function MarketFlag({ code, size = 18 }: { code: string; size?: number }) {
  if (hasFlagArt(code)) {
    return <CountryFlag code={code.toLowerCase()} size={size} className="ring-1 ring-inset ring-black/10" />;
  }
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-[13px] min-w-[18px] items-center justify-center rounded-[2px] bg-surface-tertiary px-1 text-[9px] font-bold leading-none text-content-tertiary"
    >
      {code.toUpperCase()}
    </span>
  );
}

/** Says what we can do in one direction, in the reader's language. */
function SupportChip({ level, direction }: { level: SupportLevel; direction: 'import' | 'export' }) {
  const { t } = useTranslation();
  const label =
    direction === 'import'
      ? t('exchange.direction_import', { defaultValue: 'Import' })
      : t('exchange.direction_export', { defaultValue: 'Export' });

  if (level === 'none') {
    return (
      <span className="text-2xs text-content-quaternary">
        {label}: {t('exchange.support_none', { defaultValue: 'not yet' })}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
      {level === 'native' ? (
        <Check size={11} aria-hidden="true" className="text-emerald-600" />
      ) : null}
      {label}:{' '}
      <span className={level === 'native' ? 'font-semibold text-content-secondary' : ''}>
        {level === 'native'
          ? t('exchange.support_native', { defaultValue: 'direct' })
          : t('exchange.support_assisted', { defaultValue: 'guided' })}
      </span>
    </span>
  );
}

/* ── The page ──────────────────────────────────────────────────────── */

export default function RegionalExchangeHubPage() {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [market, setMarket] = useState<string | null>(null);
  const [marketTouched, setMarketTouched] = useState(false);
  const [formatId, setFormatId] = useState<string | null>(null);
  const [tab, setTab] = useState<'import' | 'export'>('import');
  const [search, setSearch] = useState('');
  const [projectId, setProjectId] = useState('');
  const [boqId, setBoqId] = useState('');
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const { data: boqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs', projectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: Boolean(projectId),
  });

  // The project decides the market only until the reader says otherwise.
  // Without `marketTouched` a click on a flag would be undone the moment a
  // project list settled, which reads as the page refusing the click.
  const activeProject = useMemo(
    () => projects.find((p) => p.id === (projectId || activeProjectId)) ?? null,
    [projects, projectId, activeProjectId],
  );
  const inferred = useMemo(
    () => inferMarket(activeProject?.country_code ?? activeProject?.region ?? null, i18n.language),
    [activeProject, i18n.language],
  );

  useEffect(() => {
    if (!marketTouched && inferred) setMarket(inferred);
  }, [inferred, marketTouched]);

  const { data: catalogue, isLoading, isError } = useExchangeCatalogue(market);
  const formats = catalogue?.formats ?? [];

  // The default the backend picked for this market, applied whenever the
  // market changes and the reader has not chosen a format since.
  //
  // For a market the catalogue has no row for, the backend answers null
  // rather than borrowing another market's document, and the page falls
  // back to the first row it is showing for that market, which is the
  // spreadsheet row that belongs to everybody. The first row of the whole
  // catalogue is the wrong fallback: it is a German interchange container,
  // and for such a market it is not even on the page, so nothing would be
  // highlighted and the panel would offer a format nobody there has seen.
  useEffect(() => {
    if (!catalogue) return;
    setFormatId((current) => {
      if (current && catalogue.formats.some((f) => f.format_id === current)) return current;
      return catalogue.default_format_id ?? formatsForMarket(catalogue.formats, market)[0]?.format_id ?? null;
    });
  }, [catalogue, market]);

  const shown: ExchangeFormatInfo[] = useMemo(() => formatsForMarket(formats, market), [formats, market]);
  const selected = useMemo(() => formats.find((f) => f.format_id === formatId) ?? null, [formats, formatId]);

  const markets = useMemo(() => {
    // The union of what the catalogue reports and what we have a dedicated
    // screen for. The second half is what keeps this honest when the
    // catalogue request fails: twenty market screens are mounted whatever
    // the backend says, and a hub that hid them on a network error would
    // put them back where they started, mounted and reachable only by
    // typing the URL, which is the defect this page was written to close.
    const codes = new Set(marketsIn(formats));
    for (const tpl of COUNTRY_TEMPLATES) codes.add(tpl.countryCode.toUpperCase());
    const named = [...codes].map((code) => ({ code, name: regionDisplayName(code, i18n.language) }));
    named.sort((a, b) => a.name.localeCompare(b.name, i18n.language));
    const query = search.trim().toLowerCase();
    if (!query) return named;
    return named.filter(
      (entry) => entry.name.toLowerCase().includes(query) || entry.code.toLowerCase().includes(query),
    );
  }, [formats, i18n.language, search]);

  const specialist = useMemo(() => specialistPageFor(market), [market]);

  const chooseMarket = useCallback((code: string) => {
    setMarketTouched(true);
    setMarket((current) => (current === code ? null : code));
    setFormatId(null);
    setOutcome(null);
  }, []);

  /* ── Import ──────────────────────────────────────────────────────── */

  const runImport = useCallback(
    async (file: File) => {
      if (!boqId) return;
      setBusy(true);
      setOutcome(null);
      try {
        const body = new FormData();
        body.append('file', file);
        const token = getAuthToken();
        const response = await fetch(IMPORT_ENDPOINT(boqId), {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body,
        });
        const payload: Record<string, unknown> = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
          throw new Error(detail);
        }

        // `imported` is the server's count and is never substituted. A
        // number this screen made up would look exactly like a number the
        // server gave, and the one time they differ is the one time it
        // matters.
        const imported = typeof payload.imported === 'number' ? payload.imported : null;
        const rawErrors = Array.isArray(payload.errors) ? payload.errors : [];
        const errors = rawErrors.map((entry) =>
          typeof entry === 'string'
            ? entry
            : [
                (entry as { ordinal?: string })?.ordinal,
                (entry as { error?: string })?.error,
              ]
                .filter(Boolean)
                .join(': '),
        );
        setOutcome({
          imported,
          skipped: typeof payload.skipped === 'number' ? payload.skipped : 0,
          detectedFormat:
            (typeof payload.format_id === 'string' && payload.format_id) ||
            (typeof payload.source_format === 'string' && payload.source_format) ||
            '',
          method: typeof payload.method === 'string' ? payload.method : '',
          errors,
        });
        queryClient.invalidateQueries({ queryKey: ['boq-positions'] });
        addToast({
          type: imported && imported > 0 ? 'success' : 'warning',
          title: t('regional.import_complete', { defaultValue: 'Import complete' }),
          message:
            imported === null
              ? t('exchange.import_count_unknown', {
                  defaultValue: 'The server did not report how many rows it took.',
                })
              : t('exchange.import_count', {
                  defaultValue: '{{count}} positions imported',
                  count: imported,
                }),
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' });
        setOutcome({ imported: 0, skipped: 0, detectedFormat: '', method: '', errors: [message] });
        addToast({
          type: 'error',
          title: t('regional.import_failed', { defaultValue: 'Import failed' }),
          message,
        });
      } finally {
        setBusy(false);
      }
    },
    [addToast, boqId, queryClient, t],
  );

  /* ── Export ──────────────────────────────────────────────────────── */

  const runExport = useCallback(async () => {
    if (!boqId || !selected) return;
    const url = exportEndpoint(boqId, selected);
    if (!url) return;
    setBusy(true);
    try {
      const boq = boqs.find((b) => b.id === boqId);
      const stem = (boq?.name || 'boq').replace(/[^\w.-]+/g, '_');
      await downloadWithAuth(url, `${stem}${selected.export_extension ?? ''}`);
      addToast({
        type: 'success',
        title: t('regional.export_complete', { defaultValue: 'Export complete' }),
        message: selected.name,
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('regional.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setBusy(false);
    }
  }, [addToast, boqId, boqs, selected, t]);

  /* ── Render ──────────────────────────────────────────────────────── */

  const accept = selected?.extensions.join(',') ?? '.xlsx,.csv,.xml,.bc3';
  const canImport = Boolean(boqId) && selected?.import_support !== 'none';
  const canExport = Boolean(boqId) && selected?.export_support === 'native';

  return (
    <div className="space-y-5">
      <PageHeader srTitle={t('boq.preset_regional', { defaultValue: 'Regional standards' })} />

      <DismissibleInfo
        storageKey="regional-exchange-hub"
        title={t('regional.intro_title', { defaultValue: "Speak your country's tender format" })}
        more={
          t('regional.intro_more', { defaultValue: '' }) ? (
            <IntroRichText text={t('regional.intro_more')} />
          ) : undefined
        }
      >
        {t('regional.intro_body', {
          defaultValue:
            "Import and export BOQ data in your region's native structure (NRM in the UK, MasterFormat in the US, DPGF in France and others), with the right trade-section breakdown applied. The data lands in or comes from a normal BOQ, so the same estimate moves across markets without re-keying.",
        })}
      </DismissibleInfo>

      {/* ── Market strip ────────────────────────────────────────────── */}
      <section aria-label={t('exchange.markets', { defaultValue: 'Markets' })} className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xs font-semibold text-content-secondary">
            {t('exchange.markets', { defaultValue: 'Markets' })}
          </h2>
          <label className="relative">
            <Search
              size={13}
              aria-hidden="true"
              className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-content-quaternary"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="exchange-market-search"
              placeholder={t('exchange.search_market', { defaultValue: 'Find a market' })}
              aria-label={t('exchange.search_market', { defaultValue: 'Find a market' })}
              className="h-7 w-44 rounded-md border border-border-light bg-surface-primary pl-7 pr-2 text-2xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none"
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-1.5" data-testid="exchange-market-strip">
          {markets.map(({ code, name }) => {
            const active = market === code;
            return (
              <button
                key={code}
                type="button"
                onClick={() => chooseMarket(code)}
                aria-pressed={active}
                data-testid={`exchange-market-${code}`}
                title={name}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-2xs transition-colors duration-normal ease-oe focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue ${
                  active
                    ? 'border-oe-blue bg-oe-blue/10 font-semibold text-content-primary'
                    : 'border-border-light bg-surface-primary text-content-secondary hover:border-border-medium'
                }`}
              >
                <MarketFlag code={code} />
                <span className="max-w-[9rem] truncate">{name}</span>
                {code === inferred && !active ? (
                  <Badge variant="blue" size="sm">
                    {t('exchange.your_market', { defaultValue: 'Yours' })}
                  </Badge>
                ) : null}
              </button>
            );
          })}
          {markets.length === 0 && !isLoading ? (
            <p className="text-2xs text-content-tertiary">
              {t('exchange.no_market_match', { defaultValue: 'No market matches that search.' })}
            </p>
          ) : null}
        </div>
      </section>

      {/* The market's own screen, where one exists and knows more than the
          generic panel below: its trade sections, its classification code
          shape, its column layout. Deliberately outside the format panel,
          because it depends on the chosen market and not on the chosen
          format, and because a failed catalogue request must not be able to
          hide the way into twenty screens that are mounted regardless. */}
      {specialist ? (
        <Link
          to={`/${specialist.routeSlug}`}
          data-testid="exchange-specialist"
          className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-2xs font-medium text-oe-blue hover:border-oe-blue"
        >
          {t('exchange.open_specialist', {
            defaultValue: 'Open the {{market}} screen, with its trade sections and code checks',
            market: regionDisplayName(specialist.countryCode, i18n.language),
          })}
          <ArrowRight size={12} aria-hidden="true" className="rtl:rotate-180" />
        </Link>
      ) : null}

      {isError ? (
        <p className="rounded-lg border border-border-light bg-surface-primary p-4 text-xs text-content-secondary">
          {t('exchange.catalogue_unavailable', {
            defaultValue: 'The format catalogue could not be loaded, so nothing is listed rather than a stale list.',
          })}
        </p>
      ) : null}

      {/* ── Formats ─────────────────────────────────────────────────── */}
      <section aria-label={t('exchange.formats', { defaultValue: 'Formats' })} className="space-y-2">
        <h2 className="text-xs font-semibold text-content-secondary">
          {market
            ? t('exchange.formats_in', {
                defaultValue: 'Formats used in {{market}}',
                market: regionDisplayName(market, i18n.language),
              })
            : t('exchange.formats', { defaultValue: 'Formats' })}
        </h2>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="exchange-format-grid">
          {shown.map((fmt) => {
            const active = fmt.format_id === formatId;
            return (
              <button
                key={fmt.format_id}
                type="button"
                onClick={() => {
                  setFormatId(fmt.format_id);
                  setOutcome(null);
                }}
                aria-pressed={active}
                data-testid={`exchange-format-${fmt.format_id}`}
                className={`flex flex-col gap-1.5 rounded-xl border p-3 text-left transition-shadow duration-normal ease-oe hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue ${
                  active ? 'border-oe-blue bg-oe-blue/5 shadow-xs' : 'border-border-light bg-surface-primary'
                }`}
              >
                <span className="flex items-center gap-1">
                  {fmt.countries.slice(0, 4).map((code) => (
                    <MarketFlag key={code} code={code} size={16} />
                  ))}
                  {fmt.countries.length > 4 ? (
                    <span className="text-2xs text-content-quaternary">+{fmt.countries.length - 4}</span>
                  ) : null}
                  {fmt.countries.length === 0 ? (
                    <span className="text-2xs text-content-quaternary">
                      {t('exchange.any_market', { defaultValue: 'Any market' })}
                    </span>
                  ) : null}
                </span>
                <span className="text-xs font-semibold text-content-primary">{fmt.name}</span>
                <span className="text-2xs text-content-tertiary line-clamp-2">{fmt.summary}</span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 pt-0.5">
                  <SupportChip level={fmt.import_support} direction="import" />
                  <SupportChip level={fmt.export_support} direction="export" />
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── The selected format ─────────────────────────────────────── */}
      {selected ? (
        <section
          aria-label={selected.name}
          data-testid="exchange-panel"
          className="rounded-xl border border-border-light bg-surface-primary p-4"
        >
          <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-content-primary">{selected.name}</h2>
              <p className="mt-0.5 text-2xs text-content-tertiary">
                {selected.standard ? `${selected.standard} · ` : ''}
                {selected.extensions.join(' ')}
              </p>
            </div>
            <div className="flex gap-1" role="tablist">
              {(['import', 'export'] as const).map((which) => (
                <button
                  key={which}
                  type="button"
                  role="tab"
                  aria-selected={tab === which}
                  onClick={() => setTab(which)}
                  data-testid={`exchange-tab-${which}`}
                  className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-2xs transition-colors duration-normal ease-oe ${
                    tab === which
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-tertiary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  {which === 'import' ? <Upload size={12} aria-hidden="true" /> : <Download size={12} aria-hidden="true" />}
                  {which === 'import'
                    ? t('regional.tab_import', { defaultValue: 'Import' })
                    : t('regional.tab_export', { defaultValue: 'Export' })}
                </button>
              ))}
            </div>
          </header>

          {/* Where the rows go, or come from. */}
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-2xs font-medium text-content-secondary">
                {t('common.project', { defaultValue: 'Project' })}
              </span>
              <select
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setBoqId('');
                }}
                data-testid="exchange-project"
                className="h-8 w-full rounded-md border border-border-light bg-surface-primary px-2 text-xs text-content-primary"
              >
                <option value="">{t('common.select', { defaultValue: 'Select' })}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-2xs font-medium text-content-secondary">
                {t('boq.title', { defaultValue: 'Bill of quantities' })}
              </span>
              <select
                value={boqId}
                onChange={(e) => setBoqId(e.target.value)}
                disabled={!projectId}
                data-testid="exchange-boq"
                className="h-8 w-full rounded-md border border-border-light bg-surface-primary px-2 text-xs text-content-primary disabled:opacity-50"
              >
                <option value="">{t('common.select', { defaultValue: 'Select' })}</option>
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-3">
            {tab === 'import' ? (
              <div className="space-y-2">
                {selected.import_support === 'none' ? (
                  <p className="text-xs text-content-secondary">
                    {t('exchange.import_unavailable', {
                      defaultValue:
                        'We do not read this format yet. Nothing here will accept it, which is better than taking the file and losing what is in it.',
                    })}
                  </p>
                ) : (
                  <>
                    {selected.import_support === 'assisted' ? (
                      <p className="text-2xs text-content-tertiary">
                        {t('exchange.import_guided_note', {
                          defaultValue:
                            'No direct reader for this one yet, so the file goes through the guided import: it proposes a mapping and you confirm every row before anything is written.',
                        })}
                      </p>
                    ) : null}
                    <input
                      ref={fileInput}
                      type="file"
                      accept={accept}
                      className="sr-only"
                      data-testid="exchange-file"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void runImport(file);
                        e.target.value = '';
                      }}
                    />
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      disabled={!canImport || busy}
                      onClick={() => fileInput.current?.click()}
                      data-testid="exchange-import"
                    >
                      {busy ? (
                        <Loader2 size={13} aria-hidden="true" className="animate-spin" />
                      ) : (
                        <Upload size={13} aria-hidden="true" />
                      )}
                      {t('exchange.choose_file', { defaultValue: 'Choose a file' })}
                    </Button>
                    {!boqId ? (
                      <p className="text-2xs text-content-quaternary">
                        {t('exchange.pick_target', { defaultValue: 'Pick the project and BOQ the rows belong to first.' })}
                      </p>
                    ) : null}
                  </>
                )}

                {outcome ? (
                  <div className="rounded-lg bg-surface-secondary p-2.5 text-2xs" data-testid="exchange-outcome">
                    <p className="text-content-secondary">
                      {outcome.imported === null
                        ? t('exchange.import_count_unknown', {
                            defaultValue: 'The server did not report how many rows it took.',
                          })
                        : t('exchange.import_count', {
                            defaultValue: '{{count}} positions imported',
                            count: outcome.imported,
                          })}
                      {outcome.skipped > 0
                        ? ` · ${t('exchange.skipped', { defaultValue: '{{count}} rows skipped', count: outcome.skipped })}`
                        : ''}
                    </p>
                    {outcome.detectedFormat ? (
                      <p className="mt-0.5 text-content-tertiary">
                        {t('exchange.detected_as', {
                          defaultValue: 'Read as {{format}}',
                          format: outcome.detectedFormat,
                        })}
                        {outcome.method === 'smart_import'
                          ? ` · ${t('exchange.via_guided', { defaultValue: 'through the guided import' })}`
                          : ''}
                      </p>
                    ) : null}
                    {outcome.errors.length > 0 ? (
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-content-secondary">
                        {outcome.errors.slice(0, 8).map((line, idx) => (
                          <li key={idx}>{line}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="space-y-2">
                {selected.export_support === 'native' ? (
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={!canExport || busy}
                    onClick={() => void runExport()}
                    data-testid="exchange-export"
                  >
                    {busy ? (
                      <Loader2 size={13} aria-hidden="true" className="animate-spin" />
                    ) : (
                      <Download size={13} aria-hidden="true" />
                    )}
                    {t('exchange.download_as', { defaultValue: 'Download as {{format}}', format: selected.name })}
                  </Button>
                ) : (
                  <p className="text-xs text-content-secondary">
                    {t('exchange.export_unavailable', {
                      defaultValue:
                        'We do not write this format yet. A spreadsheet export of the same BOQ carries the same rows, if that helps in the meantime.',
                    })}
                  </p>
                )}
                {!boqId && selected.export_support === 'native' ? (
                  <p className="text-2xs text-content-quaternary">
                    {t('exchange.pick_source', { defaultValue: 'Pick the project and BOQ to export first.' })}
                  </p>
                ) : null}
              </div>
            )}
          </div>

        </section>
      ) : null}
    </div>
  );
}
