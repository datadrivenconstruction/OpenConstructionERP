// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings → Data feeds: read-only flat tables an estimator pastes into Excel,
 * Power Query or any BI tool as a URL.
 *
 * Top to bottom: the feeds with their size, a project and key picker that shape
 * the copied URLs, a 20-row preview of the selected feed, and the two lines a
 * person needs to connect (Excel "From Web" and a Power Query snippet carrying
 * the key header). A key is created here with only the `bi:read` scope and its
 * secret is shown once, never stored by this screen.
 */
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, KeyRound } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { copyToClipboard } from '@/shared/lib/browser';
import { fmtList } from '@/shared/lib/formatters';
import { projectsApi } from '@/features/projects/api';
import { useToastStore } from '@/stores/useToastStore';

const SCOPE = 'bi:read';
const PREVIEW_ROWS = 20;

export interface FeedInfo {
  id: string;
  title_key: string;
  columns: { name: string; kind: string }[];
  row_count: number;
}

interface FeedPreview {
  columns: { name: string; kind: string }[];
  total: number;
  rows: Record<string, string | number | boolean | null>[];
}

interface SqlStatus {
  enabled: boolean;
  schema_name: string;
  role: string;
  views: string[];
}

interface ApiKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  permissions: string[];
}

interface ApiKeyCreated extends ApiKeyRow {
  key: string;
}

const keys = {
  feeds: ['bi-feed', 'feeds'] as const,
  sql: ['bi-feed', 'sql-status'] as const,
  apiKeys: ['bi-feed', 'api-keys'] as const,
  projects: ['bi-feed', 'projects'] as const,
  preview: (feed: string, project: string) => ['bi-feed', 'preview', feed, project] as const,
};

/** API path of a feed file, scoped to a project when one is chosen. */
export function feedPath(feedId: string, ext: 'csv' | 'parquet' | 'json', projectId: string, limit?: number): string {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  if (limit) params.set('limit', String(limit));
  const query = params.toString();
  return `/v1/bi-feed/feeds/${feedId}.${ext}${query ? `?${query}` : ''}`;
}

/** Absolute URL of a feed file on this server. */
export function feedUrl(feedId: string, ext: 'csv' | 'parquet' | 'json', projectId: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return `${origin}/api${feedPath(feedId, ext, projectId)}`;
}

/** Power Query (M) that loads a feed with the key in the X-API-Key header. */
export function powerQuerySnippet(url: string, keyValue: string): string {
  return [
    'let',
    `    Source = Csv.Document(Web.Contents("${url}", [Headers = [#"X-API-Key" = "${keyValue}"]]),`,
    '        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
    '    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])',
    'in',
    '    Promoted',
  ].join('\n');
}

export function DataFeedsSettings() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState('');
  const [feedId, setFeedId] = useState('');
  const [keyId, setKeyId] = useState('');
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  const feedsQuery = useQuery({ queryKey: keys.feeds, queryFn: () => apiGet<FeedInfo[]>(`/v1/bi-feed/feeds`) });
  const projectsQuery = useQuery({ queryKey: keys.projects, queryFn: () => projectsApi.list() });
  const keysQuery = useQuery({
    queryKey: keys.apiKeys,
    queryFn: () => apiGet<ApiKeyRow[]>('/v1/users/me/api-keys/'),
  });
  const sqlQuery = useQuery({
    queryKey: keys.sql,
    queryFn: () => apiGet<SqlStatus>(`/v1/bi-feed/sql-status`).catch(() => null),
  });

  const feeds = feedsQuery.data ?? [];
  const projects = projectsQuery.data ?? [];
  const activeFeed = feedId || feeds[0]?.id || '';
  const feedKeys = (keysQuery.data ?? []).filter((k) => k.is_active && k.permissions.includes(SCOPE));
  const selectedKey = feedKeys.find((k) => k.id === keyId) ?? feedKeys[0];

  const previewQuery = useQuery({
    queryKey: keys.preview(activeFeed, projectId),
    queryFn: () => apiGet<FeedPreview>(feedPath(activeFeed, 'json', projectId, PREVIEW_ROWS)),
    enabled: Boolean(activeFeed) && projects.length > 0,
  });

  const createKey = useMutation({
    mutationFn: () =>
      apiPost<ApiKeyCreated>('/v1/users/me/api-keys/', {
        name: t('bi_feed.key_name', { defaultValue: 'Data feeds' }),
        permissions: [SCOPE],
        expires_in_days: 365,
      }),
    onSuccess: (row) => {
      setCreated(row);
      setKeyId(row.id);
      void queryClient.invalidateQueries({ queryKey: keys.apiKeys });
    },
    onError: () =>
      addToast({ type: 'error', title: t('bi_feed.key_create_failed', { defaultValue: 'Could not create the key' }) }),
  });

  const copy = async (url: string) => {
    const ok = await copyToClipboard(url);
    addToast({
      type: ok ? 'success' : 'error',
      title: ok
        ? t('bi_feed.copied', { defaultValue: 'URL copied' })
        : t('bi_feed.copy_failed', { defaultValue: 'Could not copy the URL' }),
    });
  };

  const keyValue = useMemo(() => {
    if (created && (!keyId || keyId === created.id)) return created.key;
    return selectedKey ? `${selectedKey.key_prefix}...` : t('bi_feed.key_placeholder', { defaultValue: '<your key>' });
  }, [created, keyId, selectedKey, t]);

  if (projectsQuery.isSuccess && projects.length === 0) {
    return (
      <Card data-testid="bi-feed-empty">
        <CardHeader title={t('bi_feed.title', { defaultValue: 'Data feeds' })} />
        <CardContent>
          <p className="text-sm text-content-secondary">
            {t('bi_feed.empty_projects', { defaultValue: 'Create a project first' })}
          </p>
          <Link to="/projects" className="mt-3 inline-block text-sm font-medium text-oe-blue hover:underline">
            {t('bi_feed.open_projects', { defaultValue: 'Open projects' })}
          </Link>
        </CardContent>
      </Card>
    );
  }

  const previewColumns = previewQuery.data?.columns ?? [];
  const snippetUrl = activeFeed ? feedUrl(activeFeed, 'csv', projectId) : '';

  return (
    <div className="space-y-6" data-testid="bi-feed-settings">
      <Card>
        <CardHeader
          title={t('bi_feed.title', { defaultValue: 'Data feeds' })}
          subtitle={t('bi_feed.subtitle', {
            defaultValue: 'Read-only tables for Excel, Power Query and any BI tool. Paste the URL, refresh when you need new numbers.',
          })}
        />
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-content-primary">
                {t('bi_feed.project_label', { defaultValue: 'Project' })}
              </span>
              <select
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                data-testid="bi-feed-project"
              >
                <option value="">{t('bi_feed.project_all', { defaultValue: 'All my projects' })}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-content-primary">
                {t('bi_feed.key_label', { defaultValue: 'API key' })}
              </span>
              <span className="flex gap-2">
                <select
                  className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm"
                  value={selectedKey?.id ?? ''}
                  onChange={(e) => setKeyId(e.target.value)}
                  data-testid="bi-feed-key"
                >
                  {feedKeys.length === 0 && (
                    <option value="">{t('bi_feed.key_none', { defaultValue: 'No key with bi:read yet' })}</option>
                  )}
                  {feedKeys.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name} ({k.key_prefix}...)
                    </option>
                  ))}
                </select>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<KeyRound size={14} />}
                  onClick={() => createKey.mutate()}
                  disabled={createKey.isPending}
                  data-testid="bi-feed-create-key"
                >
                  {t('bi_feed.create_key', { defaultValue: 'Create key with bi:read' })}
                </Button>
              </span>
            </label>
          </div>

          {created && (
            <div
              className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm"
              role="status"
              data-testid="bi-feed-new-key"
            >
              <p className="font-medium text-content-primary">
                {t('bi_feed.key_created', { defaultValue: 'Copy this key now. It is shown only once.' })}
              </p>
              <code className="mt-2 block break-all rounded bg-surface-secondary px-2 py-1 font-mono text-xs">
                {created.key}
              </code>
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="secondary" icon={<Copy size={14} />} onClick={() => void copy(created.key)}>
                  {t('bi_feed.copy_key', { defaultValue: 'Copy key' })}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setCreated(null)} data-testid="bi-feed-dismiss-key">
                  {t('bi_feed.key_done', { defaultValue: 'I have saved it' })}
                </Button>
              </div>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="bi-feed-table">
              <thead>
                <tr className="border-b border-border-light text-xs uppercase text-content-tertiary">
                  <th className="py-2 pr-4">{t('bi_feed.col_feed', { defaultValue: 'Feed' })}</th>
                  <th className="py-2 pr-4 text-right">{t('bi_feed.col_columns', { defaultValue: 'Columns' })}</th>
                  <th className="py-2 pr-4 text-right">{t('bi_feed.col_rows', { defaultValue: 'Rows' })}</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {feeds.map((f) => (
                  <tr
                    key={f.id}
                    className={`border-b border-border-light/60 ${f.id === activeFeed ? 'bg-oe-blue/[0.04]' : ''}`}
                  >
                    <td className="py-2 pr-4">
                      <button
                        type="button"
                        className="font-medium text-content-primary hover:underline"
                        onClick={() => setFeedId(f.id)}
                        aria-pressed={f.id === activeFeed}
                      >
                        {t(f.title_key, { defaultValue: f.id })}
                      </button>
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{f.columns.length}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{f.row_count}</td>
                    <td className="py-2">
                      <span className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={<Copy size={14} />}
                          onClick={() => void copy(feedUrl(f.id, 'csv', projectId))}
                          data-testid={`bi-feed-copy-csv-${f.id}`}
                        >
                          {t('bi_feed.copy_csv', { defaultValue: 'Copy CSV URL' })}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={<Copy size={14} />}
                          onClick={() => void copy(feedUrl(f.id, 'parquet', projectId))}
                          data-testid={`bi-feed-copy-parquet-${f.id}`}
                        >
                          {t('bi_feed.copy_parquet', { defaultValue: 'Copy Parquet URL' })}
                        </Button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('bi_feed.preview_title', { defaultValue: 'Preview' })}
          subtitle={t('bi_feed.preview_subtitle', { defaultValue: 'The first 20 rows of the selected feed' })}
        />
        <CardContent>
          {previewQuery.isLoading && (
            <p className="text-sm text-content-secondary">{t('bi_feed.loading', { defaultValue: 'Loading' })}</p>
          )}
          {previewQuery.isError && (
            <p className="text-sm text-semantic-error">
              {t('bi_feed.load_error', { defaultValue: 'Could not load the preview' })}
            </p>
          )}
          {previewQuery.isSuccess && previewQuery.data.rows.length === 0 && (
            <p className="text-sm text-content-secondary">
              {t('bi_feed.preview_empty', { defaultValue: 'No rows yet' })}
            </p>
          )}
          {previewQuery.isSuccess && previewQuery.data.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs" data-testid="bi-feed-preview">
                <thead>
                  <tr className="border-b border-border-light text-content-tertiary">
                    {previewColumns.map((c) => (
                      <th key={c.name} className="whitespace-nowrap py-1 pr-3">
                        {c.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewQuery.data.rows.map((row, i) => (
                    <tr key={i} className="border-b border-border-light/60">
                      {previewColumns.map((c) => (
                        <td
                          key={c.name}
                          className={`whitespace-nowrap py-1 pr-3 ${c.kind === 'money' || c.kind === 'decimal' ? 'text-right tabular-nums' : ''}`}
                        >
                          {row[c.name] === null || row[c.name] === undefined ? '' : String(row[c.name])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader title={t('bi_feed.connect_title', { defaultValue: 'Connect Excel or Power BI' })} />
        <CardContent className="space-y-3">
          <p className="text-sm text-content-secondary" data-testid="bi-feed-excel-hint">
            {t('bi_feed.excel_hint', { defaultValue: 'Excel: Data > From Web > paste the URL' })}
          </p>
          <p className="text-sm font-medium text-content-primary">
            {t('bi_feed.powerquery_title', { defaultValue: 'Power Query with the key header' })}
          </p>
          <pre
            className="overflow-x-auto rounded-lg bg-surface-secondary p-3 font-mono text-xs"
            data-testid="bi-feed-powerquery"
          >
            {powerQuerySnippet(snippetUrl, keyValue)}
          </pre>
        </CardContent>
      </Card>

      {sqlQuery.data?.enabled && (
        <Card data-testid="bi-feed-sql">
          <CardHeader title={t('bi_feed.sql_title', { defaultValue: 'SQL access' })} />
          <CardContent className="space-y-1 text-sm text-content-secondary">
            <p>
              {t('bi_feed.sql_hint', {
                defaultValue: 'Connect any SQL tool to the PostgreSQL database with the read-only role below.',
              })}
            </p>
            <p className="font-mono text-xs">
              {t('bi_feed.sql_role', { defaultValue: 'Role' })}: {sqlQuery.data.role}
            </p>
            <p className="font-mono text-xs">
              {t('bi_feed.sql_views', { defaultValue: 'Views' })}: {fmtList(sqlQuery.data.views.map((v) => `${sqlQuery.data?.schema_name}.${v}`))}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
