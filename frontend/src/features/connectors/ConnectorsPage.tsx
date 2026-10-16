// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Document Connectors - pull files that live in scattered places onto the
// project record. Register a watched folder, then "Sync now" scans it and
// imports each new file as a first-class, searchable project document,
// deduplicated so the same file is never imported twice. Each source shows the
// outcome of its last sync (found / imported / already on record / duplicate)
// and when it ran, so an admin can see at a glance what a connector is doing.
// Registering and syncing require an admin role (they read server-local paths).

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, FolderPlus, FolderSync, Inbox, Search } from 'lucide-react';

import { Card, EmptyState, SkeletonTable, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { listConnectorSources, createConnectorSource, syncConnectorSource } from './api';
import { SourceCard } from './SourceCard';
import { ConnectorsSummary } from './ConnectorsSummary';
import { sourceMatchesQuery } from './utils';

type StatusFilter = 'all' | 'enabled' | 'disabled';

// Long-form walkthrough revealed behind the intro's "Show more". Uses the
// IntroRichText markdown subset (numbered list + bold lead-ins). Kept as a
// module constant so the JSX below stays readable.
const INTRO_MORE = [
  '**How a file becomes a project record:**',
  '',
  '1. **Folder.** An operator points a connector at a folder on the server, inside the connectors area (for example a site drop share or a scan-to-folder destination).',
  '2. **Capture.** Each sync scans that folder, reads every file and fingerprints it, so the same file is never brought in twice.',
  '3. **Inbound.** New files are registered on the project and show up in Inbound Capture alongside captured email and chat, so everything that arrives lands in one place.',
  '4. **Records.** From there each file is a first-class project document: searchable, on the timeline and ready to attach to correspondence, BOQ items or issues.',
  '',
  'Syncing is manual and admin-only today, and it only reads. It never moves, renames or deletes anything in the watched folder.',
].join('\n');

export function ConnectorsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId ?? activeProjectId ?? '';
  const inboundPath = routeProjectId ? `/projects/${routeProjectId}/inbound` : '/inbound';

  const [name, setName] = useState('');
  const [rootPath, setRootPath] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const sourcesQuery = useQuery({
    queryKey: ['connectors', 'sources', projectId],
    queryFn: () => listConnectorSources(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createConnectorSource(projectId, { name: name.trim(), root_path: rootPath.trim() }),
    onSuccess: () => {
      setName('');
      setRootPath('');
      void queryClient.invalidateQueries({ queryKey: ['connectors', 'sources', projectId] });
    },
  });

  const syncMutation = useMutation({
    mutationFn: (sourceId: string) => syncConnectorSource(sourceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['connectors', 'sources', projectId] });
    },
  });

  const canAdd = !!projectId && name.trim() !== '' && rootPath.trim() !== '';

  if (!projectId) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<FolderSync className="h-6 w-6" />}
          title={t('connectors.no_project_title', { defaultValue: 'No project selected' })}
          description={t('connectors.no_project_desc', {
            defaultValue: 'Select a project to register inbound document connectors for it.',
          })}
        />
      </div>
    );
  }

  const sources = sourcesQuery.data ?? [];
  const filtered = sources.filter((s) => {
    if (statusFilter === 'enabled' && !s.enabled) return false;
    if (statusFilter === 'disabled' && s.enabled) return false;
    return sourceMatchesQuery(s, query);
  });
  const filterActive = query.trim() !== '' || statusFilter !== 'all';
  const lastSyncedId = syncMutation.variables;

  const clearFilter = () => {
    setQuery('');
    setStatusFilter('all');
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="flex flex-wrap items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <FolderSync className="h-5 w-5" />
        </span>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-content-primary">
            {t('connectors.title', { defaultValue: 'Document Connectors' })}
          </h1>
          <p className="text-sm text-content-secondary">
            {t('connectors.subtitle', {
              defaultValue: 'Bring documents from scattered places onto the project record.',
            })}
          </p>
        </div>
        <Link
          to={inboundPath}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
        >
          {t('connectors.view_inbound', { defaultValue: 'View inbound capture' })}
          <ArrowRight className="h-4 w-4" />
        </Link>
      </header>

      <DismissibleInfo
        storageKey="connectors-intro"
        title={t('connectors.intro_title', { defaultValue: 'How connectors work' })}
        more={<IntroRichText text={t('connectors.intro_more', { defaultValue: INTRO_MORE })} />}
        links={[
          {
            label: t('connectors.open_inbound', { defaultValue: 'Open Inbound Capture' }),
            onClick: () => navigate(inboundPath),
          },
        ]}
      >
        {t('connectors.intro_body', {
          defaultValue:
            'Point a connector at a folder on the server. Each sync scans it and brings in every new file as a project document, so documents stored outside the system still land on the record and are searchable. Files already imported are skipped, and two copies of the same file are detected and not duplicated.',
        })}
      </DismissibleInfo>

      {sources.length > 0 ? <ConnectorsSummary sources={sources} /> : null}

      <Card className="space-y-3 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <FolderPlus className="h-4 w-4" />
          {t('connectors.add_title', { defaultValue: 'Add a watched folder' })}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('connectors.name', { defaultValue: 'Name' })}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('connectors.name_ph', { defaultValue: 'Site drop folder' })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('connectors.root_path', { defaultValue: 'Folder path (on the server)' })}
            <input
              value={rootPath}
              onChange={(e) => setRootPath(e.target.value)}
              placeholder={t('connectors.root_path_ph', { defaultValue: '/data/inbound/site-a' })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>
        </div>

        {createMutation.isError && (
          <p className="text-sm text-semantic-error">{getErrorMessage(createMutation.error)}</p>
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!canAdd || createMutation.isPending}
            onClick={() => createMutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FolderPlus className="h-4 w-4" />
            {t('connectors.add_source', { defaultValue: 'Add connector' })}
          </button>
          <span className="text-xs text-content-tertiary">
            {t('connectors.admin_hint', {
              defaultValue: 'Registering and syncing a connector require an admin role.',
            })}
          </span>
        </div>
      </Card>

      <div className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <FolderSync className="h-4 w-4" />
          {t('connectors.sources', { defaultValue: 'Connectors' })}
        </h2>

        {sources.length >= 2 && !sourcesQuery.isError ? (
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[12rem] flex-1">
              <Search className="pointer-events-none absolute start-2 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('connectors.filter_search_ph', {
                  defaultValue: 'Search by name or path',
                })}
                className="w-full rounded-md border border-border-light bg-surface-primary py-1.5 ps-8 pe-2 text-sm text-content-primary"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              aria-label={t('connectors.filter_status_label', { defaultValue: 'Filter by status' })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
            >
              <option value="all">{t('connectors.filter_all', { defaultValue: 'All' })}</option>
              <option value="enabled">{t('connectors.enabled', { defaultValue: 'Enabled' })}</option>
              <option value="disabled">
                {t('connectors.disabled', { defaultValue: 'Disabled' })}
              </option>
            </select>
            {filterActive ? (
              <span className="text-xs text-content-tertiary">
                {t('connectors.showing_count', {
                  defaultValue: 'Showing {{shown}} of {{total}}',
                  shown: filtered.length,
                  total: sources.length,
                })}
              </span>
            ) : null}
          </div>
        ) : null}

        {sourcesQuery.isLoading ? (
          <SkeletonTable rows={2} />
        ) : sourcesQuery.isError ? (
          <EmptyState
            icon={<Inbox className="h-6 w-6" />}
            title={t('connectors.error_title', { defaultValue: 'Could not load connectors' })}
            description={getErrorMessage(sourcesQuery.error)}
          />
        ) : sources.length === 0 ? (
          <EmptyState
            icon={<FolderSync className="h-6 w-6" />}
            title={t('connectors.empty_title', { defaultValue: 'No connectors yet' })}
            description={t('connectors.empty_desc', {
              defaultValue:
                'Add a watched folder above to start bringing its documents onto the record.',
            })}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Search className="h-6 w-6" />}
            title={t('connectors.no_matches_title', { defaultValue: 'No matching connectors' })}
            description={t('connectors.no_matches_desc', {
              defaultValue: 'No connectors match your filter. Clear it to see them all.',
            })}
            action={{
              label: t('connectors.clear_filter', { defaultValue: 'Clear filter' }),
              onClick: clearFilter,
            }}
          />
        ) : (
          <div className="space-y-3">
            {filtered.map((source) => {
              const isLast = lastSyncedId === source.id;
              return (
                <SourceCard
                  key={source.id}
                  source={source}
                  onSync={(id) => syncMutation.mutate(id)}
                  syncing={syncMutation.isPending && isLast}
                  syncError={isLast && syncMutation.isError ? syncMutation.error : undefined}
                  syncResult={isLast && syncMutation.isSuccess ? syncMutation.data : null}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default ConnectorsPage;
