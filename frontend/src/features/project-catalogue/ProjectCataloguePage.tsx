// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project Catalogue - the active project's own rates and resources.
 *
 * Rates are copied from the cost database or the resource catalogue (or typed
 * in), edited for this job only, and keep the source they came from. When a
 * source price moves the row says so and the estimator takes the new price or
 * keeps the local one. Bill lines priced from a rate can be refreshed in one
 * step after the rate changes. The master data is never written from here.
 */

import { useMemo, useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { BookCopy, Check, Database, Link2, Plus, RefreshCw, Trash2, Undo2 } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  Input,
  KpiBand,
  MoneyDisplay,
  PageHeader,
  Skeleton,
  WideModal,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  applyItem,
  createItem,
  deleteItem,
  formatDeviation,
  importItems,
  listCandidates,
  listItems,
  needsDecision,
  pushItem,
  searchSources,
  statusVariant,
  syncItems,
  updateItem,
  type CatalogueItem,
  type CatalogueSourceType,
  type CatalogueStatus,
  type SyncAction,
} from './api';

const QK = (projectId: string | null) => ['project-catalogue', projectId] as const;
const FILTERS: ('' | CatalogueStatus)[] = ['', 'source_changed', 'overridden', 'manual'];

export function ProjectCataloguePage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [ownOpen, setOwnOpen] = useState(false);

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('project_catalogue.title', { defaultValue: 'Project Catalogue' })}
        subtitle={t('project_catalogue.subtitle', {
          defaultValue: "This project's own rates, copied from the cost database and edited without changing it.",
        })}
        actions={
          projectId ? (
            <>
              <Button variant="primary" icon={<Database className="h-4 w-4" />} onClick={() => setSourceOpen(true)}>
                {t('project_catalogue.add_from_source', { defaultValue: 'Add from database' })}
              </Button>
              <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setOwnOpen(true)}>
                {t('project_catalogue.add_own', { defaultValue: 'Add own rate' })}
              </Button>
            </>
          ) : undefined
        }
      />
      <DismissibleInfo
        storageKey="project_catalogue"
        title={t('project_catalogue.intro_title', {
          defaultValue: 'Price this job without touching the master database',
        })}
      >
        {t('project_catalogue.intro_body', {
          defaultValue:
            'Each rate remembers where it came from. When the source price moves you decide: take the new price or keep yours. Bill lines priced from a rate follow it when you push.',
        })}
      </DismissibleInfo>
      {projectId ? (
        <CatalogueContent projectId={projectId} />
      ) : (
        <EmptyState
          icon={<BookCopy className="h-10 w-10" />}
          title={t('project_catalogue.no_project', { defaultValue: 'Select a project to see its catalogue' })}
        />
      )}
      {projectId && sourceOpen && <SourceModal projectId={projectId} onClose={() => setSourceOpen(false)} />}
      {projectId && ownOpen && <OwnRateModal projectId={projectId} onClose={() => setOwnOpen(false)} />}
    </div>
  );
}

function useCatalogueToasts() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return {
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
    done: (title: string) => addToast({ type: 'success', title }),
  };
}

function CatalogueContent({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { onError, done } = useCatalogueToasts();
  const [filter, setFilter] = useState<'' | CatalogueStatus>('');
  const [applyFor, setApplyFor] = useState<CatalogueItem | null>(null);
  const q = useQuery({ queryKey: QK(projectId), queryFn: () => listItems(projectId) });
  const refresh = () => qc.invalidateQueries({ queryKey: QK(projectId) });

  const syncMut = useMutation({
    mutationFn: ({ action, ids }: { action: SyncAction; ids?: string[] }) => syncItems(projectId, action, ids),
    onSuccess: (res) => {
      refresh();
      done(t('project_catalogue.synced', { defaultValue: 'Rates updated: {{n}}', n: res.updated }));
    },
    onError,
  });
  const rateMut = useMutation({
    mutationFn: ({ id, rate }: { id: string; rate: string }) => updateItem(id, { rate }),
    onSuccess: refresh,
    onError,
  });
  const pushMut = useMutation({
    mutationFn: (id: string) => pushItem(id),
    onSuccess: (res) => {
      refresh();
      done(t('project_catalogue.pushed', { defaultValue: 'Bill lines re-priced: {{n}}', n: res.applied }));
    },
    onError,
  });
  const deleteMut = useMutation({ mutationFn: (id: string) => deleteItem(id), onSuccess: refresh, onError });

  const items = useMemo(
    () => (q.data?.items ?? []).filter((i) => !filter || i.status === filter),
    [q.data, filter],
  );

  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) {
    return (
      <ErrorState
        title={t('project_catalogue.load_error', { defaultValue: 'Could not load the project catalogue' })}
        onRetry={() => q.refetch()}
      />
    );
  }
  const s = q.data.summary;
  if (s.total === 0) {
    return (
      <EmptyState
        icon={<BookCopy className="h-10 w-10" />}
        title={t('project_catalogue.empty', { defaultValue: 'No rates in this project yet' })}
        description={t('project_catalogue.empty_hint', {
          defaultValue: 'Copy rates from the cost database or add your own, then price bill lines from them.',
        })}
      />
    );
  }

  return (
    <>
      <KpiBand
        columns={4}
        items={[
          { key: 'total', label: t('project_catalogue.kpi_rates', { defaultValue: 'Rates' }), value: s.total },
          {
            key: 'overridden',
            label: t('project_catalogue.status_overridden', { defaultValue: 'Local price' }),
            value: s.overridden,
            tone: 'blue',
          },
          {
            key: 'changed',
            label: t('project_catalogue.status_source_changed', { defaultValue: 'Source changed' }),
            value: s.source_changed,
            tone: s.source_changed ? 'warning' : 'default',
          },
          {
            key: 'lines',
            label: t('project_catalogue.kpi_lines', { defaultValue: 'Bill lines priced' }),
            value: s.linked_positions,
            sub: s.stale_positions
              ? t('project_catalogue.kpi_stale', { defaultValue: 'Out of date: {{n}}', n: s.stale_positions })
              : undefined,
            tone: s.stale_positions ? 'warning' : 'default',
          },
        ]}
      />

      {s.source_changed > 0 && (
        <Card className="flex flex-wrap items-center justify-between gap-2 border-semantic-warning/30 bg-semantic-warning-bg">
          <span className="text-sm text-content-primary">
            {t('project_catalogue.decide_banner', {
              defaultValue: 'Source prices moved since copying: {{n}}. Decide per rate or for all at once.',
              n: s.source_changed,
            })}
          </span>
          <span className="flex gap-2">
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />}
              loading={syncMut.isPending} onClick={() => syncMut.mutate({ action: 'take_source' })}>
              {t('project_catalogue.take_all', { defaultValue: 'Take all new prices' })}
            </Button>
            <Button size="sm" variant="ghost" icon={<Check className="h-3.5 w-3.5" />}
              loading={syncMut.isPending} onClick={() => syncMut.mutate({ action: 'keep_local' })}>
              {t('project_catalogue.keep_all', { defaultValue: 'Keep all local prices' })}
            </Button>
          </span>
        </Card>
      )}

      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light p-3">
          <div role="group" className="inline-flex h-8 items-center rounded-lg border border-border bg-surface-primary p-0.5">
            {FILTERS.map((f) => (
              <button
                key={f || 'all'}
                data-oe-segment
                type="button"
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
                className={clsx(
                  'h-full rounded-sm px-2.5 text-xs font-medium',
                  filter === f
                    ? 'bg-surface-tertiary text-content-primary'
                    : 'text-content-secondary hover:text-content-primary',
                )}
              >
                {f ? statusLabel(t, f) : t('project_catalogue.filter_all', { defaultValue: 'All' })}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="oe-table">
            <thead>
              <tr>
                <th>{t('project_catalogue.col_code', { defaultValue: 'Code' })}</th>
                <th>{t('project_catalogue.col_description', { defaultValue: 'Description' })}</th>
                <th>{t('project_catalogue.col_unit', { defaultValue: 'Unit' })}</th>
                <th className="text-right">{t('project_catalogue.col_rate', { defaultValue: 'Project rate' })}</th>
                <th>{t('project_catalogue.col_source', { defaultValue: 'Source' })}</th>
                <th>{t('project_catalogue.col_status', { defaultValue: 'Status' })}</th>
                <th className="text-right">{t('project_catalogue.col_lines', { defaultValue: 'Lines' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="font-mono text-xs">{item.code}</td>
                  <td className="max-w-xs truncate" title={item.description}>{item.description}</td>
                  <td>{item.unit}</td>
                  <td className="text-right">
                    <RateCell item={item} onSave={(rate) => rateMut.mutate({ id: item.id, rate })} />
                  </td>
                  <td className="text-xs text-content-secondary">
                    {item.source_type === 'manual' ? (
                      t('project_catalogue.status_manual', { defaultValue: 'Own rate' })
                    ) : (
                      <span title={item.source_code}>
                        {item.source_label || item.source_code}
                        {item.current_source_rate != null && (
                          <span className="ml-1 text-content-tertiary">
                            <MoneyDisplay amount={item.current_source_rate} currency={item.source_currency} />
                          </span>
                        )}
                      </span>
                    )}
                  </td>
                  <td>
                    <Badge variant={statusVariant(item.status)} size="sm">{statusLabel(t, item.status)}</Badge>
                    {formatDeviation(item.deviation_percent) && (
                      <span className="ml-1 text-2xs text-content-tertiary">{formatDeviation(item.deviation_percent)}</span>
                    )}
                  </td>
                  <td className="text-right text-xs">
                    {item.linked_positions}
                    {item.stale_positions > 0 && (
                      <span className="ml-1 text-semantic-warning">
                        {t('project_catalogue.stale_short', { defaultValue: 'old: {{n}}', n: item.stale_positions })}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className="flex justify-end gap-1">
                      {needsDecision(item) && (
                        <>
                          <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />}
                            aria-label={t('project_catalogue.take_source', { defaultValue: 'Take new source price' })}
                            title={t('project_catalogue.take_source', { defaultValue: 'Take new source price' })}
                            onClick={() => syncMut.mutate({ action: 'take_source', ids: [item.id] })} />
                          <Button size="sm" variant="ghost" icon={<Check className="h-3.5 w-3.5" />}
                            aria-label={t('project_catalogue.keep_local', { defaultValue: 'Keep local price' })}
                            title={t('project_catalogue.keep_local', { defaultValue: 'Keep local price' })}
                            onClick={() => syncMut.mutate({ action: 'keep_local', ids: [item.id] })} />
                        </>
                      )}
                      {item.status === 'overridden' && (
                        <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />}
                          aria-label={t('project_catalogue.reset_to_source', { defaultValue: 'Back to source price' })}
                          title={t('project_catalogue.reset_to_source', { defaultValue: 'Back to source price' })}
                          onClick={() => syncMut.mutate({ action: 'take_source', ids: [item.id] })} />
                      )}
                      <Button size="sm" variant="ghost" icon={<Link2 className="h-3.5 w-3.5" />}
                        aria-label={t('project_catalogue.apply', { defaultValue: 'Price bill lines' })}
                        title={t('project_catalogue.apply', { defaultValue: 'Price bill lines' })}
                        onClick={() => setApplyFor(item)} />
                      {item.stale_positions > 0 && (
                        <Button size="sm" variant="secondary"
                          loading={pushMut.isPending} onClick={() => pushMut.mutate(item.id)}>
                          {t('project_catalogue.push', { defaultValue: 'Update lines' })}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        onClick={() => deleteMut.mutate(item.id)} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {applyFor && <ApplyModal item={applyFor} onClose={() => setApplyFor(null)} />}
    </>
  );
}

function statusLabel(t: (k: string, o?: Record<string, unknown>) => string, status: CatalogueStatus): string {
  switch (status) {
    case 'in_sync':
      return t('project_catalogue.status_in_sync', { defaultValue: 'As source' });
    case 'overridden':
      return t('project_catalogue.status_overridden', { defaultValue: 'Local price' });
    case 'source_changed':
      return t('project_catalogue.status_source_changed', { defaultValue: 'Source changed' });
    case 'source_missing':
      return t('project_catalogue.status_source_missing', { defaultValue: 'Source removed' });
    default:
      return t('project_catalogue.status_manual', { defaultValue: 'Own rate' });
  }
}

function RateCell({ item, onSave }: { item: CatalogueItem; onSave: (rate: string) => void }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<string | null>(null);
  if (draft === null) {
    return (
      <button type="button" className="font-mono text-sm hover:text-oe-blue"
        title={t('project_catalogue.edit_rate', { defaultValue: 'Edit the project rate' })}
        onClick={() => setDraft(item.rate)}>
        <MoneyDisplay amount={item.rate} currency={item.currency} />
      </button>
    );
  }
  const commit = () => {
    const next = draft.trim().replace(',', '.');
    setDraft(null);
    if (next && next !== item.rate) onSave(next);
  };
  return (
    <input
      autoFocus
      inputMode="decimal"
      className="oe-input-sm w-28 text-right font-mono"
      aria-label={t('project_catalogue.edit_rate', { defaultValue: 'Edit the project rate' })}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') setDraft(null);
      }}
    />
  );
}

function SourceModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { onError, done } = useCatalogueToasts();
  const [sourceType, setSourceType] = useState<CatalogueSourceType>('cost_item');
  const [text, setText] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const search = useQuery({
    queryKey: ['project-catalogue-sources', projectId, sourceType, text],
    queryFn: () => searchSources(projectId, sourceType, text.trim()),
    enabled: text.trim().length >= 2,
  });
  const importMut = useMutation({
    mutationFn: () => importItems(projectId, sourceType, [...picked]),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: QK(projectId) });
      done(t('project_catalogue.imported', { defaultValue: 'Rates copied into the project: {{n}}', n: res.added }));
      onClose();
    },
    onError,
  });
  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('project_catalogue.add_from_source', { defaultValue: 'Add from database' })}
      subtitle={t('project_catalogue.source_hint', {
        defaultValue: 'The copies belong to this project. The database itself is not changed.',
      })}
      footer={
        <Button variant="primary" disabled={picked.size === 0} loading={importMut.isPending}
          onClick={() => importMut.mutate()}>
          {t('project_catalogue.copy_n', { defaultValue: 'Copy into project ({{n}})', n: picked.size })}
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" className="inline-flex h-8 items-center rounded-lg border border-border bg-surface-primary p-0.5">
            {(['cost_item', 'catalog_resource'] as CatalogueSourceType[]).map((st) => (
              <button key={st} data-oe-segment type="button" aria-pressed={sourceType === st}
                onClick={() => { setSourceType(st); setPicked(new Set()); }}
                className={clsx('h-full rounded-sm px-2.5 text-xs font-medium',
                  sourceType === st ? 'bg-surface-tertiary text-content-primary' : 'text-content-secondary hover:text-content-primary')}>
                {st === 'cost_item'
                  ? t('project_catalogue.source_cost_items', { defaultValue: 'Cost database' })
                  : t('project_catalogue.source_resources', { defaultValue: 'Resource catalogue' })}
              </button>
            ))}
          </div>
          <input className="oe-input flex-1" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t('project_catalogue.search_ph', { defaultValue: 'Search by code or description' })} />
        </div>
        {search.isFetching ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <table className="oe-table oe-table-compact">
            <tbody>
              {(search.data?.items ?? []).map((hit) => (
                <tr key={hit.source_id}>
                  <td className="w-8">
                    <input type="checkbox" disabled={hit.already_added} checked={hit.already_added || picked.has(hit.source_id)}
                      aria-label={hit.code} onChange={() => toggle(hit.source_id)} />
                  </td>
                  <td className="font-mono text-xs">{hit.code}</td>
                  <td>{hit.description}</td>
                  <td>{hit.unit}</td>
                  <td className="text-right"><MoneyDisplay amount={hit.rate} currency={hit.currency} /></td>
                  <td className="text-xs text-content-tertiary">
                    {hit.already_added ? t('project_catalogue.already_added', { defaultValue: 'In project' }) : hit.label}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </WideModal>
  );
}

function OwnRateModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { onError } = useCatalogueToasts();
  const [form, setForm] = useState({ code: '', description: '', unit: '', rate: '', currency: '' });
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const createMut = useMutation({
    mutationFn: () => createItem(projectId, { ...form, rate: form.rate.trim().replace(',', '.') || '0' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK(projectId) });
      onClose();
    },
    onError,
  });
  const ready = form.code.trim() && form.description.trim() && form.unit.trim();
  return (
    <WideModal
      open
      onClose={onClose}
      size="md"
      title={t('project_catalogue.add_own', { defaultValue: 'Add own rate' })}
      footer={
        <Button variant="primary" disabled={!ready} loading={createMut.isPending} onClick={() => createMut.mutate()}>
          {t('project_catalogue.save', { defaultValue: 'Save rate' })}
        </Button>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Input label={t('project_catalogue.col_code', { defaultValue: 'Code' })} value={form.code} onChange={set('code')} />
        <Input label={t('project_catalogue.col_unit', { defaultValue: 'Unit' })} value={form.unit} onChange={set('unit')} />
        <div className="col-span-2">
          <Input label={t('project_catalogue.col_description', { defaultValue: 'Description' })}
            value={form.description} onChange={set('description')} />
        </div>
        <Input label={t('project_catalogue.col_rate', { defaultValue: 'Project rate' })} inputMode="decimal"
          value={form.rate} onChange={set('rate')} />
        <Input label={t('project_catalogue.currency', { defaultValue: 'Currency' })} value={form.currency}
          onChange={set('currency')} placeholder="EUR" />
      </div>
    </WideModal>
  );
}

function ApplyModal({ item, onClose }: { item: CatalogueItem; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { onError, done } = useCatalogueToasts();
  const [text, setText] = useState('');
  const [sameUnit, setSameUnit] = useState(true);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const lines = useQuery({
    queryKey: ['project-catalogue-lines', item.id, text, sameUnit],
    queryFn: () => listCandidates(item.id, text.trim(), sameUnit),
  });
  const applyMut = useMutation({
    mutationFn: () => applyItem(item.id, [...picked]),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: QK(item.project_id) });
      done(t('project_catalogue.applied', { defaultValue: 'Bill lines priced: {{n}}', n: res.applied }));
      onClose();
    },
    onError,
  });
  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('project_catalogue.apply_title', { defaultValue: 'Price bill lines from {{code}}', code: item.code })}
      footer={
        <Button variant="primary" disabled={picked.size === 0} loading={applyMut.isPending} onClick={() => applyMut.mutate()}>
          {t('project_catalogue.apply_n', { defaultValue: 'Price lines ({{n}})', n: picked.size })}
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <input className="oe-input flex-1" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t('project_catalogue.search_lines_ph', { defaultValue: 'Search bill lines' })} />
          <label className="inline-flex items-center gap-1.5 text-sm text-content-secondary">
            <input type="checkbox" checked={sameUnit} onChange={(e) => setSameUnit(e.target.checked)} />
            {t('project_catalogue.same_unit', { defaultValue: 'Same unit only ({{unit}})', unit: item.unit })}
          </label>
        </div>
        {lines.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (lines.data?.items.length ?? 0) === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('project_catalogue.no_lines', { defaultValue: 'No matching bill lines in this project.' })}
          </p>
        ) : (
          <table className="oe-table oe-table-compact">
            <tbody>
              {lines.data?.items.map((line) => (
                <tr key={line.id}>
                  <td className="w-8">
                    <input type="checkbox" aria-label={line.ordinal} checked={picked.has(line.id)}
                      onChange={() => setPicked((prev) => {
                        const next = new Set(prev);
                        if (next.has(line.id)) next.delete(line.id);
                        else next.add(line.id);
                        return next;
                      })} />
                  </td>
                  <td className="text-xs text-content-tertiary">{line.boq_name}</td>
                  <td className="font-mono text-xs">{line.ordinal}</td>
                  <td>{line.description}</td>
                  <td>{line.unit}</td>
                  <td className="text-right font-mono text-xs">{line.unit_rate}</td>
                  <td className="text-xs text-content-tertiary">
                    {line.linked_item_id === item.id ? t('project_catalogue.linked', { defaultValue: 'Linked' }) : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </WideModal>
  );
}
