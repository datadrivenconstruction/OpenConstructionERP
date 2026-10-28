// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Activity codes / UDFs / saved layouts panel (T2.3). A self-contained view
// mode mounted in SchedulePage, modelled on the sibling schedule panels. Three
// in-panel tabs (local state):
//
//   - Dictionaries & values: list / create / delete the project's code
//     dictionaries, import a library template, and edit a selected
//     dictionary's hierarchical values (indented by depth).
//   - User-defined fields: list / create / delete the project's UDFs (typed:
//     text / number / date / bool / enum, with an enum-values editor).
//   - Grouped view: the workhorse grid. Pick 1-3 code-dictionary group-by
//     levels, run the server-side grouped query, and browse banded groups
//     interleaved with their activity rows (expand/collapse, pagination,
//     save-as-layout + apply/delete saved layouts).
//
// All paths/shapes are derived from backend codes_router.py / codes_schemas.py
// / codes_grouped.py. Group expand/collapse uses the band ``path`` (the
// ``(none)`` band uses the sentinel ``__none__``); a row sits under a band when
// the band path is a prefix of the row's ``group_path``.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Tags,
  Plus,
  Trash2,
  Loader2,
  Library,
  Play,
  Layers,
  ChevronRight,
  ChevronDown,
  Save,
  FolderOpen,
  AlertTriangle,
  Hash,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  scheduleApi,
  buildLayoutSpec,
  GROUP_NONE_KEY,
  type CodeDictionary,
  type CodeValue,
  type ScheduleUdf,
  type UdfValueType,
  type LayoutGroupBy,
  type LayoutShareScope,
  type GroupedResponse,
} from './api';
import { fmtList } from '@/shared/lib/formatters';

interface ScheduleCodesPanelProps {
  scheduleId: string;
  projectId: string;
}

type TabKey = 'dictionaries' | 'udfs' | 'grouped';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

const UDF_VALUE_TYPES: UdfValueType[] = ['text', 'number', 'date', 'bool', 'enum'];
const SHARE_SCOPES: LayoutShareScope[] = ['private', 'project', 'workspace'];

/** Join a band/group path into a single, stable expand/collapse identifier.
 *  The separator is the ASCII unit separator, built from its code point so the
 *  source stays plain text; it cannot occur in a value-id UUID or the "(none)"
 *  key, so distinct group paths never collide onto the same expand-state key. */
function pathId(path: string[]): string {
  return path.join(String.fromCharCode(31));
}

export function ScheduleCodesPanel({ scheduleId, projectId }: ScheduleCodesPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [tab, setTab] = useState<TabKey>('dictionaries');

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  const tabs: { key: TabKey; label: string; icon: typeof Tags }[] = [
    {
      key: 'dictionaries',
      label: t('schedule.codes.tab_dictionaries', { defaultValue: 'Dictionaries & values' }),
      icon: Tags,
    },
    {
      key: 'udfs',
      label: t('schedule.codes.tab_udfs', { defaultValue: 'User-defined fields' }),
      icon: Hash,
    },
    {
      key: 'grouped',
      label: t('schedule.codes.tab_grouped', { defaultValue: 'Grouped view' }),
      icon: Layers,
    },
  ];

  return (
    <div className="space-y-4" data-testid="schedule-codes-panel">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <Tags size={18} className="text-content-secondary" />
        <h3 className="text-base font-semibold text-content-primary">
          {t('schedule.codes.title', { defaultValue: 'Activity codes, fields & layouts' })}
        </h3>
      </div>
      <p className="-mt-2 text-xs text-content-secondary">
        {t('schedule.codes.subtitle', {
          defaultValue:
            'Organise activities with hierarchical code dictionaries and user-defined fields, then slice the schedule into a grouped, banded grid and save the view as a reusable layout.',
        })}
      </p>

      {/* ── Tab switcher ───────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 rounded-lg border border-border-light p-0.5">
        {tabs.map((tb) => {
          const Icon = tb.icon;
          const active = tab === tb.key;
          return (
            <button
              key={tb.key}
              type="button"
              aria-pressed={active}
              onClick={() => setTab(tb.key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                active ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              <Icon size={13} />
              {tb.label}
            </button>
          );
        })}
      </div>

      {tab === 'dictionaries' ? (
        <DictionariesTab projectId={projectId} onError={toastError} />
      ) : tab === 'udfs' ? (
        <UdfsTab projectId={projectId} onError={toastError} />
      ) : (
        <GroupedTab scheduleId={scheduleId} projectId={projectId} onError={toastError} />
      )}
    </div>
  );
}

/* ── Tab 1: Dictionaries & values ─────────────────────────────────────────── */

function DictionariesTab({
  projectId,
  onError,
}: {
  projectId: string;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [selectedDictId, setSelectedDictId] = useState<string | null>(null);
  const [showLibrary, setShowLibrary] = useState(false);

  const dictsKey = ['schedule', 'codes', 'dictionaries', projectId];
  const dictsQ = useQuery<CodeDictionary[]>({
    queryKey: dictsKey,
    queryFn: () => scheduleApi.listCodeDictionaries(projectId),
    enabled: !!projectId,
  });

  const invalidateDicts = () => queryClient.invalidateQueries({ queryKey: dictsKey });

  // Create dictionary form
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [colorBand, setColorBand] = useState(true);
  const [sortOrder, setSortOrder] = useState('0');

  const createMut = useMutation({
    mutationFn: () =>
      scheduleApi.createCodeDictionary(projectId, {
        name: name.trim(),
        description: description.trim(),
        color_band: colorBand,
        sort_order: Number(sortOrder) || 0,
      }),
    onSuccess: (d) => {
      setName('');
      setDescription('');
      setColorBand(true);
      setSortOrder('0');
      setSelectedDictId(d.id);
      invalidateDicts();
      addToast({
        type: 'success',
        title: t('schedule.codes.dict_created', { defaultValue: 'Dictionary created' }),
        message: t('schedule.codes.dict_created_msg', {
          defaultValue: 'Add values to "{{name}}" below.',
          name: d.name,
        }),
      });
    },
    onError,
  });

  const deleteDictMut = useMutation({
    mutationFn: (dictId: string) => scheduleApi.deleteCodeDictionary(dictId),
    onSuccess: (_res, dictId) => {
      if (selectedDictId === dictId) setSelectedDictId(null);
      invalidateDicts();
      addToast({
        type: 'success',
        title: t('schedule.codes.dict_deleted', { defaultValue: 'Dictionary deleted' }),
        message: t('schedule.codes.dict_deleted_msg', {
          defaultValue: 'The dictionary and its values were removed.',
        }),
      });
    },
    onError,
  });

  const onDeleteDict = (d: CodeDictionary) => {
    if (
      window.confirm(
        t('schedule.codes.dict_delete_confirm', {
          defaultValue: 'Delete dictionary "{{name}}" and all its values?',
          name: d.name,
        }),
      )
    ) {
      deleteDictMut.mutate(d.id);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
      {/* Left: list + create */}
      <div className="space-y-4">
        <Card padding="none">
          <div className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-3">
            <h4 className="text-sm font-semibold text-content-primary">
              {t('schedule.codes.dictionaries', { defaultValue: 'Code dictionaries' })}
            </h4>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowLibrary((v) => !v)}
              icon={<Library size={14} />}
            >
              {t('schedule.codes.import_library', { defaultValue: 'Import from library' })}
            </Button>
          </div>

          {dictsQ.isLoading ? (
            <div className="p-4">
              <SkeletonTable rows={4} columns={1} />
            </div>
          ) : dictsQ.isError ? (
            <div className="p-4">
              <RecoveryCard error={dictsQ.error} onRetry={() => dictsQ.refetch()} />
            </div>
          ) : (dictsQ.data?.length ?? 0) === 0 ? (
            <div className="px-4 py-6">
              <p className="text-sm text-content-tertiary">
                {t('schedule.codes.dicts_empty', {
                  defaultValue: 'No code dictionaries yet. Create one below or import a template.',
                })}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border-light" data-testid="codes-dictionary-list">
              {dictsQ.data!.map((d) => {
                const active = d.id === selectedDictId;
                return (
                  <li key={d.id} className="flex items-center">
                    <button
                      type="button"
                      onClick={() => setSelectedDictId(d.id)}
                      aria-pressed={active}
                      className={`flex min-w-0 flex-1 items-center gap-2 px-4 py-3 text-left transition-colors ${
                        active ? 'bg-oe-blue-subtle/50' : 'hover:bg-surface-secondary/40'
                      }`}
                    >
                      {d.color_band && (
                        <span className="inline-block h-3 w-3 shrink-0 rounded-sm bg-oe-blue/40" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-content-primary">
                          {d.name}
                        </span>
                        {d.description && (
                          <span className="block truncate text-2xs text-content-tertiary">
                            {d.description}
                          </span>
                        )}
                      </span>
                      <ChevronRight size={14} className="shrink-0 text-content-tertiary" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteDict(d)}
                      disabled={deleteDictMut.isPending}
                      aria-label={t('schedule.codes.delete_dict', { defaultValue: 'Delete dictionary' })}
                      className="mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {showLibrary && (
            <LibraryImporter projectId={projectId} onImported={invalidateDicts} onError={onError} />
          )}
        </Card>

        {/* Create dictionary */}
        <Card padding="md">
          <h4 className="mb-3 text-sm font-semibold text-content-primary">
            {t('schedule.codes.new_dict', { defaultValue: 'New dictionary' })}
          </h4>
          <div className="space-y-3">
            <div>
              <label htmlFor="codes-dict-name" className={labelCls}>
                {t('schedule.codes.name', { defaultValue: 'Name' })}
              </label>
              <input
                id="codes-dict-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('schedule.codes.dict_name_ph', {
                  defaultValue: 'e.g. Area, Discipline, Subcontractor',
                })}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="codes-dict-desc" className={labelCls}>
                {t('schedule.codes.description', { defaultValue: 'Description' })}
              </label>
              <input
                id="codes-dict-desc"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="flex items-center gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
                <input
                  type="checkbox"
                  checked={colorBand}
                  onChange={(e) => setColorBand(e.target.checked)}
                  className="h-4 w-4 rounded border-border accent-oe-blue"
                />
                {t('schedule.codes.color_band', { defaultValue: 'Colour bands' })}
              </label>
              <div className="ml-auto w-24">
                <label htmlFor="codes-dict-sort" className={labelCls}>
                  {t('schedule.codes.sort_order', { defaultValue: 'Sort' })}
                </label>
                <input
                  id="codes-dict-sort"
                  type="number"
                  min={0}
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
            <Button
              variant="primary"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending || name.trim().length === 0}
              icon={
                createMut.isPending ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Plus size={16} />
                )
              }
            >
              {t('schedule.codes.create_dict', { defaultValue: 'Create dictionary' })}
            </Button>
          </div>
        </Card>
      </div>

      {/* Right: selected dictionary values */}
      <div className="min-w-0">
        {!selectedDictId ? (
          <Card padding="md">
            <EmptyState
              icon={<Tags size={28} strokeWidth={1.5} />}
              title={t('schedule.codes.select_dict', { defaultValue: 'Select a dictionary' })}
              description={t('schedule.codes.select_dict_desc', {
                defaultValue:
                  'Choose a dictionary on the left to view and edit its values. Values can nest under one another to build a hierarchy (for example a region containing several sites).',
              })}
            />
          </Card>
        ) : (
          <DictionaryValues dictId={selectedDictId} onError={onError} />
        )}
      </div>
    </div>
  );
}

/* ── Library importer ─────────────────────────────────────────────────────── */

function LibraryImporter({
  projectId,
  onImported,
  onError,
}: {
  projectId: string;
  onImported: () => void;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const libQ = useQuery<CodeDictionary[]>({
    queryKey: ['schedule', 'codes', 'library'],
    queryFn: () => scheduleApi.listLibraryDictionaries(),
  });

  const importMut = useMutation({
    mutationFn: (libraryDictionaryId: string) =>
      scheduleApi.importLibraryDictionary(projectId, libraryDictionaryId),
    onSuccess: (d) => {
      onImported();
      addToast({
        type: 'success',
        title: t('schedule.codes.imported', { defaultValue: 'Dictionary imported' }),
        message: t('schedule.codes.imported_msg', {
          defaultValue: '"{{name}}" was copied into this project.',
          name: d.name,
        }),
      });
    },
    onError,
  });

  return (
    <div className="border-t border-border-light bg-surface-secondary/20 px-4 py-4">
      <h5 className="mb-2 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
        {t('schedule.codes.library_templates', { defaultValue: 'Library templates' })}
      </h5>
      {libQ.isLoading ? (
        <SkeletonTable rows={2} columns={1} />
      ) : libQ.isError ? (
        <RecoveryCard error={libQ.error} onRetry={() => libQ.refetch()} />
      ) : (libQ.data?.length ?? 0) === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('schedule.codes.library_empty', { defaultValue: 'No library templates available.' })}
        </p>
      ) : (
        <ul className="space-y-1.5" data-testid="codes-library-list">
          {libQ.data!.map((d) => (
            <li
              key={d.id}
              className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
            >
              <span className="min-w-0 flex-1 truncate text-sm text-content-primary">{d.name}</span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => importMut.mutate(d.id)}
                disabled={importMut.isPending}
                icon={
                  importMut.isPending ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Plus size={13} />
                  )
                }
              >
                {t('schedule.codes.import', { defaultValue: 'Import' })}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Dictionary values editor ─────────────────────────────────────────────── */

function DictionaryValues({
  dictId,
  onError,
}: {
  dictId: string;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const valuesKey = ['schedule', 'codes', 'values', dictId];
  const valuesQ = useQuery<CodeValue[]>({
    queryKey: valuesKey,
    queryFn: () => scheduleApi.listCodeValues(dictId),
    enabled: !!dictId,
  });

  const invalidateValues = () => queryClient.invalidateQueries({ queryKey: valuesKey });

  // Add value form
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');
  const [color, setColor] = useState('');
  const [parentId, setParentId] = useState('');
  const [sortOrder, setSortOrder] = useState('0');

  const addMut = useMutation({
    mutationFn: () =>
      scheduleApi.createCodeValue(dictId, {
        code: code.trim(),
        label: label.trim(),
        color: color.trim(),
        parent_id: parentId || null,
        sort_order: Number(sortOrder) || 0,
      }),
    onSuccess: () => {
      setCode('');
      setLabel('');
      setColor('');
      setParentId('');
      setSortOrder('0');
      invalidateValues();
      addToast({
        type: 'success',
        title: t('schedule.codes.value_added', { defaultValue: 'Value added' }),
        message: t('schedule.codes.value_added_msg', {
          defaultValue: 'The code value was added to the dictionary.',
        }),
      });
    },
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: (valueId: string) => scheduleApi.deleteCodeValue(valueId),
    onSuccess: () => {
      invalidateValues();
      addToast({
        type: 'success',
        title: t('schedule.codes.value_deleted', { defaultValue: 'Value deleted' }),
        message: t('schedule.codes.value_deleted_msg', {
          defaultValue: 'The code value was removed.',
        }),
      });
    },
    onError,
  });

  const onDeleteValue = (v: CodeValue) => {
    if (
      window.confirm(
        t('schedule.codes.value_delete_confirm', {
          defaultValue: 'Delete value "{{code}}"?',
          code: v.code,
        }),
      )
    ) {
      deleteMut.mutate(v.id);
    }
  };

  return (
    <Card padding="none">
      <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
        <h4 className="text-sm font-semibold text-content-primary">
          {t('schedule.codes.values', { defaultValue: 'Values' })}
        </h4>
        {valuesQ.data && (
          <Badge variant="neutral" size="sm">
            {valuesQ.data.length}
          </Badge>
        )}
      </div>

      {valuesQ.isLoading ? (
        <div className="p-4">
          <SkeletonTable rows={4} columns={2} />
        </div>
      ) : valuesQ.isError ? (
        <div className="p-4">
          <RecoveryCard error={valuesQ.error} onRetry={() => valuesQ.refetch()} />
        </div>
      ) : (valuesQ.data?.length ?? 0) === 0 ? (
        <div className="px-4 py-6 text-sm text-content-tertiary">
          {t('schedule.codes.values_empty', {
            defaultValue: 'No values yet. Add the first one below.',
          })}
        </div>
      ) : (
        <ul className="divide-y divide-border-light" data-testid="codes-value-list">
          {valuesQ.data!.map((v) => (
            <li key={v.id} className="flex items-center gap-2 px-4 py-2.5">
              <span style={{ paddingLeft: `${v.depth * 16}px` }} className="flex min-w-0 flex-1 items-center gap-2">
                {v.color ? (
                  <span
                    className="inline-block h-3 w-3 shrink-0 rounded-sm"
                    style={{ backgroundColor: v.color }}
                  />
                ) : (
                  <span className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border-light" />
                )}
                <span className="shrink-0 font-mono text-xs font-semibold text-content-primary">
                  {v.code}
                </span>
                {v.label && (
                  <span className="min-w-0 truncate text-sm text-content-secondary">{v.label}</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => onDeleteValue(v)}
                disabled={deleteMut.isPending}
                aria-label={t('schedule.codes.delete_value', { defaultValue: 'Delete value' })}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Add value form */}
      <div className="border-t border-border-light bg-surface-secondary/20 px-4 py-4">
        <h5 className="mb-3 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('schedule.codes.add_value', { defaultValue: 'Add value' })}
        </h5>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="codes-val-code" className={labelCls}>
              {t('schedule.codes.code', { defaultValue: 'Code' })}
            </label>
            <input
              id="codes-val-code"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={t('schedule.codes.code_ph', { defaultValue: 'e.g. A1' })}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="codes-val-label" className={labelCls}>
              {t('schedule.codes.label', { defaultValue: 'Label' })}
            </label>
            <input
              id="codes-val-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('schedule.codes.label_ph', { defaultValue: 'e.g. Block A' })}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="codes-val-parent" className={labelCls}>
              {t('schedule.codes.parent', { defaultValue: 'Parent (optional)' })}
            </label>
            <select
              id="codes-val-parent"
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('schedule.codes.no_parent', { defaultValue: 'No parent (top level)' })}
              </option>
              {(valuesQ.data ?? []).map((v) => (
                <option key={v.id} value={v.id}>
                  {`${'- '.repeat(v.depth)}${v.code}${v.label ? ` ${v.label}` : ''}`}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="codes-val-color" className={labelCls}>
                {t('schedule.codes.color', { defaultValue: 'Colour' })}
              </label>
              <input
                id="codes-val-color"
                type="text"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                placeholder="#2563eb"
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="codes-val-sort" className={labelCls}>
                {t('schedule.codes.sort_order', { defaultValue: 'Sort' })}
              </label>
              <input
                id="codes-val-sort"
                type="number"
                min={0}
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
        </div>
        <div className="mt-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => addMut.mutate()}
            disabled={addMut.isPending || code.trim().length === 0}
            icon={
              addMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />
            }
          >
            {t('schedule.codes.add_value_btn', { defaultValue: 'Add value' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/* ── Tab 2: User-defined fields ───────────────────────────────────────────── */

function UdfsTab({ projectId, onError }: { projectId: string; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const udfsKey = ['schedule', 'codes', 'udfs', projectId];
  const udfsQ = useQuery<ScheduleUdf[]>({
    queryKey: udfsKey,
    queryFn: () => scheduleApi.listUdfs(projectId),
    enabled: !!projectId,
  });
  const invalidateUdfs = () => queryClient.invalidateQueries({ queryKey: udfsKey });

  // Create UDF form
  const [key, setKey] = useState('');
  const [label, setLabel] = useState('');
  const [valueType, setValueType] = useState<UdfValueType>('text');
  const [enumText, setEnumText] = useState('');
  const [sortOrder, setSortOrder] = useState('0');

  const KEY_RE = /^[a-z][a-z0-9_]*$/;
  const keyValid = KEY_RE.test(key.trim());

  const createMut = useMutation({
    mutationFn: () => {
      const enumValues =
        valueType === 'enum'
          ? enumText
              .split('\n')
              .map((s) => s.trim())
              .filter((s) => s.length > 0)
          : [];
      return scheduleApi.createUdf(projectId, {
        key: key.trim(),
        label: label.trim(),
        value_type: valueType,
        enum_values: enumValues,
        sort_order: Number(sortOrder) || 0,
      });
    },
    onSuccess: (u) => {
      setKey('');
      setLabel('');
      setValueType('text');
      setEnumText('');
      setSortOrder('0');
      invalidateUdfs();
      addToast({
        type: 'success',
        title: t('schedule.codes.udf_created', { defaultValue: 'Field created' }),
        message: t('schedule.codes.udf_created_msg', {
          defaultValue: 'The "{{key}}" field is ready to use.',
          key: u.key,
        }),
      });
    },
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: (udfId: string) => scheduleApi.deleteUdf(udfId),
    onSuccess: () => {
      invalidateUdfs();
      addToast({
        type: 'success',
        title: t('schedule.codes.udf_deleted', { defaultValue: 'Field deleted' }),
        message: t('schedule.codes.udf_deleted_msg', {
          defaultValue: 'The user-defined field was removed.',
        }),
      });
    },
    onError,
  });

  const onDeleteUdf = (u: ScheduleUdf) => {
    if (
      window.confirm(
        t('schedule.codes.udf_delete_confirm', {
          defaultValue: 'Delete field "{{key}}"?',
          key: u.key,
        }),
      )
    ) {
      deleteMut.mutate(u.id);
    }
  };

  const typeLabel = (vt: UdfValueType): string =>
    ({
      text: t('schedule.codes.type_text', { defaultValue: 'Text' }),
      number: t('schedule.codes.type_number', { defaultValue: 'Number' }),
      date: t('schedule.codes.type_date', { defaultValue: 'Date' }),
      bool: t('schedule.codes.type_bool', { defaultValue: 'Yes / no' }),
      enum: t('schedule.codes.type_enum', { defaultValue: 'List (enum)' }),
    })[vt];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
      {/* List */}
      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.codes.udfs', { defaultValue: 'User-defined fields' })}
          </h4>
          {udfsQ.data && (
            <Badge variant="neutral" size="sm">
              {udfsQ.data.length}
            </Badge>
          )}
        </div>

        {udfsQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={4} columns={2} />
          </div>
        ) : udfsQ.isError ? (
          <div className="p-4">
            <RecoveryCard error={udfsQ.error} onRetry={() => udfsQ.refetch()} />
          </div>
        ) : (udfsQ.data?.length ?? 0) === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('schedule.codes.udfs_empty', {
              defaultValue: 'No user-defined fields yet. Create one on the right.',
            })}
          </div>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="codes-udf-list">
            {udfsQ.data!.map((u) => (
              <li key={u.id} className="flex items-center gap-2 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-content-primary">
                      {u.key}
                    </span>
                    <Badge variant="neutral" size="sm">
                      {typeLabel(u.value_type)}
                    </Badge>
                  </div>
                  {u.label && (
                    <p className="mt-0.5 truncate text-sm text-content-secondary">{u.label}</p>
                  )}
                  {u.value_type === 'enum' && u.enum_values.length > 0 && (
                    <p className="mt-0.5 truncate text-2xs text-content-tertiary">
                      {fmtList(u.enum_values)}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onDeleteUdf(u)}
                  disabled={deleteMut.isPending}
                  aria-label={t('schedule.codes.delete_udf', { defaultValue: 'Delete field' })}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Create form */}
      <Card padding="md">
        <h4 className="mb-3 text-sm font-semibold text-content-primary">
          {t('schedule.codes.new_udf', { defaultValue: 'New field' })}
        </h4>
        <div className="space-y-3">
          <div>
            <label htmlFor="codes-udf-key" className={labelCls}>
              {t('schedule.codes.udf_key', { defaultValue: 'Key' })}
            </label>
            <input
              id="codes-udf-key"
              type="text"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={t('schedule.codes.udf_key_ph', { defaultValue: 'e.g. cost_code' })}
              className={inputCls}
            />
            {key.trim().length > 0 && !keyValid && (
              <p className="mt-1 text-2xs text-semantic-error">
                {t('schedule.codes.udf_key_invalid', {
                  defaultValue: 'Start with a lowercase letter; use lowercase letters, digits and underscores only.',
                })}
              </p>
            )}
          </div>
          <div>
            <label htmlFor="codes-udf-label" className={labelCls}>
              {t('schedule.codes.label', { defaultValue: 'Label' })}
            </label>
            <input
              id="codes-udf-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('schedule.codes.udf_label_ph', { defaultValue: 'e.g. Cost code' })}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="codes-udf-type" className={labelCls}>
              {t('schedule.codes.value_type', { defaultValue: 'Value type' })}
            </label>
            <select
              id="codes-udf-type"
              value={valueType}
              onChange={(e) => setValueType(e.target.value as UdfValueType)}
              className={inputCls}
            >
              {UDF_VALUE_TYPES.map((vt) => (
                <option key={vt} value={vt}>
                  {typeLabel(vt)}
                </option>
              ))}
            </select>
          </div>
          {valueType === 'enum' && (
            <div>
              <label htmlFor="codes-udf-enum" className={labelCls}>
                {t('schedule.codes.enum_values', { defaultValue: 'List values (one per line)' })}
              </label>
              <textarea
                id="codes-udf-enum"
                value={enumText}
                onChange={(e) => setEnumText(e.target.value)}
                rows={4}
                placeholder={t('schedule.codes.enum_values_ph', {
                  defaultValue: 'Low\nMedium\nHigh',
                })}
                className={`${inputCls} h-auto py-2`}
              />
            </div>
          )}
          <div className="w-28">
            <label htmlFor="codes-udf-sort" className={labelCls}>
              {t('schedule.codes.sort_order', { defaultValue: 'Sort' })}
            </label>
            <input
              id="codes-udf-sort"
              type="number"
              min={0}
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
              className={inputCls}
            />
          </div>
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending || !keyValid}
            icon={
              createMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Plus size={16} />
              )
            }
          >
            {t('schedule.codes.create_udf', { defaultValue: 'Create field' })}
          </Button>
        </div>
      </Card>
    </div>
  );
}

/* ── Tab 3: Grouped view ──────────────────────────────────────────────────── */

interface GroupByLevel {
  dictionaryId: string;
  colorBand: boolean;
}

function GroupedTab({
  scheduleId,
  projectId,
  onError,
}: {
  scheduleId: string;
  projectId: string;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // Dictionaries drive the group-by pickers.
  const dictsQ = useQuery<CodeDictionary[]>({
    queryKey: ['schedule', 'codes', 'dictionaries', projectId],
    queryFn: () => scheduleApi.listCodeDictionaries(projectId),
    enabled: !!projectId,
  });

  // Builder state: 1-3 group-by levels (each a code dictionary).
  const [levels, setLevels] = useState<GroupByLevel[]>([{ dictionaryId: '', colorBand: true }]);
  const [timescale, setTimescale] = useState<'day' | 'week' | 'month' | 'quarter' | 'year'>('week');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<GroupedResponse | null>(null);

  const dictName = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of dictsQ.data ?? []) map.set(d.id, d.name);
    return (id: string) => map.get(id) ?? id;
  }, [dictsQ.data]);

  const activeGroupBy = useMemo<LayoutGroupBy[]>(
    () =>
      levels
        .filter((l) => l.dictionaryId)
        .map((l) => ({ key: `code:${l.dictionaryId}`, color_band: l.colorBand })),
    [levels],
  );

  const runMut = useMutation({
    // group_by / timescale are passed explicitly so callers (Run, paging,
    // expand/collapse, Apply-layout) run against the intended spec rather than a
    // possibly-stale closure over builder state.
    mutationFn: (vars: {
      page: number;
      expanded: string[];
      groupBy: LayoutGroupBy[];
      timescale: 'day' | 'week' | 'month' | 'quarter' | 'year';
    }) =>
      scheduleApi.groupedActivities(scheduleId, {
        spec: buildLayoutSpec(vars.groupBy, vars.timescale),
        page: vars.page,
        page_size: pageSize,
        expanded_groups: vars.expanded,
      }),
    onSuccess: (data) => setResult(data),
    onError,
  });

  const run = (
    nextPage: number,
    nextExpanded: Set<string>,
    groupBy: LayoutGroupBy[] = activeGroupBy,
    ts: 'day' | 'week' | 'month' | 'quarter' | 'year' = timescale,
  ) => {
    setPage(nextPage);
    runMut.mutate({ page: nextPage, expanded: Array.from(nextExpanded), groupBy, timescale: ts });
  };

  const onRunClick = () => {
    // Start collapsed; the user expands the bands they want to drill into.
    setExpanded(new Set());
    run(1, new Set());
  };

  const toggleGroup = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      run(page, next);
      return next;
    });
  };

  // Level editing
  const addLevel = () => {
    if (levels.length >= 3) return;
    setLevels((ls) => [...ls, { dictionaryId: '', colorBand: true }]);
  };
  const removeLevel = (idx: number) =>
    setLevels((ls) => (ls.length <= 1 ? ls : ls.filter((_, i) => i !== idx)));
  const setLevelDict = (idx: number, dictionaryId: string) =>
    setLevels((ls) => ls.map((l, i) => (i === idx ? { ...l, dictionaryId } : l)));
  const setLevelBand = (idx: number, colorBand: boolean) =>
    setLevels((ls) => ls.map((l, i) => (i === idx ? { ...l, colorBand } : l)));

  // Saved layouts
  const layoutsKey = ['schedule', 'codes', 'layouts', scheduleId];
  const layoutsQ = useQuery({
    queryKey: layoutsKey,
    queryFn: () => scheduleApi.listLayouts(scheduleId),
    enabled: !!scheduleId,
  });
  const invalidateLayouts = () => queryClient.invalidateQueries({ queryKey: layoutsKey });

  const [layoutName, setLayoutName] = useState('');
  const [shareScope, setShareScope] = useState<LayoutShareScope>('private');

  const saveLayoutMut = useMutation({
    mutationFn: () =>
      scheduleApi.createLayout(scheduleId, {
        name: layoutName.trim(),
        share_scope: shareScope,
        spec: buildLayoutSpec(activeGroupBy, timescale),
      }),
    onSuccess: (layout) => {
      setLayoutName('');
      invalidateLayouts();
      addToast({
        type: 'success',
        title: t('schedule.codes.layout_saved', { defaultValue: 'Layout saved' }),
        message: t('schedule.codes.layout_saved_msg', {
          defaultValue: 'Layout "{{name}}" was saved.',
          name: layout.name,
        }),
      });
    },
    onError,
  });

  const deleteLayoutMut = useMutation({
    mutationFn: (layoutId: string) => scheduleApi.deleteLayout(layoutId),
    onSuccess: () => {
      invalidateLayouts();
      addToast({
        type: 'success',
        title: t('schedule.codes.layout_deleted', { defaultValue: 'Layout deleted' }),
        message: t('schedule.codes.layout_deleted_msg', { defaultValue: 'The layout was removed.' }),
      });
    },
    onError,
  });

  // Apply a saved layout: load its code-group-by levels into the builder + run.
  const applyLayout = (spec: Record<string, unknown>) => {
    const rawGroupBy = Array.isArray(spec.group_by) ? (spec.group_by as Array<Record<string, unknown>>) : [];
    const applied: GroupByLevel[] = [];
    for (const gb of rawGroupBy) {
      const k = typeof gb.key === 'string' ? gb.key : '';
      if (k.startsWith('code:')) {
        applied.push({
          dictionaryId: k.slice('code:'.length),
          colorBand: gb.color_band !== false,
        });
      }
    }
    const nextLevels = applied.length > 0 ? applied.slice(0, 3) : [{ dictionaryId: '', colorBand: true }];
    setLevels(nextLevels);
    const ts = spec.timescale;
    const nextTs: 'day' | 'week' | 'month' | 'quarter' | 'year' =
      ts === 'day' || ts === 'week' || ts === 'month' || ts === 'quarter' || ts === 'year' ? ts : 'week';
    setTimescale(nextTs);
    // Run immediately with the applied group-by (passed explicitly so we do not
    // depend on the just-set state having flushed).
    const groupBy: LayoutGroupBy[] = nextLevels
      .filter((l) => l.dictionaryId)
      .map((l) => ({ key: `code:${l.dictionaryId}`, color_band: l.colorBand }));
    setExpanded(new Set());
    if (groupBy.length > 0) run(1, new Set(), groupBy, nextTs);
  };

  const noLevels = activeGroupBy.length === 0;

  return (
    <div className="space-y-4">
      {/* ── Builder ────────────────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center gap-2">
          <Layers size={16} className="text-content-secondary" />
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.codes.group_by', { defaultValue: 'Group by' })}
          </h4>
        </div>

        {dictsQ.isLoading ? (
          <SkeletonTable rows={2} columns={2} />
        ) : (dictsQ.data?.length ?? 0) === 0 ? (
          <div className="flex items-start gap-2 text-sm text-content-secondary">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
            <p>
              {t('schedule.codes.no_dicts_for_group', {
                defaultValue:
                  'Create at least one code dictionary first (in the Dictionaries tab), then group the schedule by it here.',
              })}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {levels.map((lvl, idx) => (
              <div key={idx} className="flex flex-wrap items-end gap-3">
                <div className="min-w-[200px] flex-1">
                  <label className={labelCls}>
                    {t('schedule.codes.level_n', { defaultValue: 'Level {{n}}', n: idx + 1 })}
                  </label>
                  <select
                    value={lvl.dictionaryId}
                    onChange={(e) => setLevelDict(idx, e.target.value)}
                    aria-label={t('schedule.codes.level_n', { defaultValue: 'Level {{n}}', n: idx + 1 })}
                    className={inputCls}
                  >
                    <option value="">
                      {t('schedule.codes.pick_dict', { defaultValue: 'Select a dictionary...' })}
                    </option>
                    {(dictsQ.data ?? []).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                <label className="flex h-9 cursor-pointer items-center gap-2 text-sm text-content-secondary">
                  <input
                    type="checkbox"
                    checked={lvl.colorBand}
                    onChange={(e) => setLevelBand(idx, e.target.checked)}
                    className="h-4 w-4 rounded border-border accent-oe-blue"
                  />
                  {t('schedule.codes.color_band', { defaultValue: 'Colour bands' })}
                </label>
                <button
                  type="button"
                  onClick={() => removeLevel(idx)}
                  disabled={levels.length <= 1}
                  aria-label={t('schedule.codes.remove_level', { defaultValue: 'Remove level' })}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors enabled:hover:bg-semantic-error-bg enabled:hover:text-semantic-error disabled:opacity-40"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={addLevel}
                disabled={levels.length >= 3}
                icon={<Plus size={14} />}
              >
                {t('schedule.codes.add_level', { defaultValue: 'Add level' })}
              </Button>
              <div className="flex items-center gap-2">
                <label htmlFor="codes-timescale" className="text-2xs uppercase tracking-wide text-content-secondary">
                  {t('schedule.codes.timescale', { defaultValue: 'Timescale' })}
                </label>
                <select
                  id="codes-timescale"
                  value={timescale}
                  onChange={(e) =>
                    setTimescale(e.target.value as 'day' | 'week' | 'month' | 'quarter' | 'year')
                  }
                  className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                >
                  {(['day', 'week', 'month', 'quarter', 'year'] as const).map((ts) => (
                    <option key={ts} value={ts}>
                      {t(`schedule.zoom_${ts}`, {
                        defaultValue: ts.charAt(0).toUpperCase() + ts.slice(1),
                      })}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={onRunClick}
                disabled={runMut.isPending || noLevels}
                icon={
                  runMut.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Play size={14} />
                  )
                }
              >
                {t('schedule.codes.run', { defaultValue: 'Run' })}
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* ── Save / apply layouts ───────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center gap-2">
          <Save size={16} className="text-content-secondary" />
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.codes.layouts', { defaultValue: 'Saved layouts' })}
          </h4>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label htmlFor="codes-layout-name" className={labelCls}>
              {t('schedule.codes.layout_name', { defaultValue: 'Layout name' })}
            </label>
            <input
              id="codes-layout-name"
              type="text"
              value={layoutName}
              onChange={(e) => setLayoutName(e.target.value)}
              placeholder={t('schedule.codes.layout_name_ph', {
                defaultValue: 'e.g. By area then discipline',
              })}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="codes-layout-scope" className={labelCls}>
              {t('schedule.codes.share_scope', { defaultValue: 'Visible to' })}
            </label>
            <select
              id="codes-layout-scope"
              value={shareScope}
              onChange={(e) => setShareScope(e.target.value as LayoutShareScope)}
              className={inputCls}
            >
              {SHARE_SCOPES.map((s) => (
                <option key={s} value={s}>
                  {t(`schedule.codes.scope_${s}`, {
                    defaultValue:
                      s === 'private' ? 'Only me' : s === 'project' ? 'This project' : 'Workspace',
                  })}
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => saveLayoutMut.mutate()}
            disabled={saveLayoutMut.isPending || layoutName.trim().length === 0 || noLevels}
            icon={
              saveLayoutMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )
            }
          >
            {t('schedule.codes.save_layout', { defaultValue: 'Save as layout' })}
          </Button>
        </div>

        <div className="mt-4 border-t border-border-light pt-3">
          {layoutsQ.isLoading ? (
            <SkeletonTable rows={2} columns={1} />
          ) : layoutsQ.isError ? (
            <RecoveryCard error={layoutsQ.error} onRetry={() => layoutsQ.refetch()} />
          ) : (layoutsQ.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('schedule.codes.layouts_empty', {
                defaultValue: 'No saved layouts yet. Build a grouping above and save it.',
              })}
            </p>
          ) : (
            <ul className="space-y-1.5" data-testid="codes-layout-list">
              {layoutsQ.data!.map((layout) => (
                <li
                  key={layout.id}
                  className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
                >
                  <FolderOpen size={14} className="shrink-0 text-content-tertiary" />
                  <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                    {layout.name}
                  </span>
                  <Badge variant="neutral" size="sm">
                    {t(`schedule.codes.scope_${layout.share_scope}`, {
                      defaultValue: layout.share_scope,
                    })}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => applyLayout(layout.spec)}
                    icon={<Play size={13} />}
                  >
                    {t('schedule.codes.apply', { defaultValue: 'Apply' })}
                  </Button>
                  <button
                    type="button"
                    onClick={() => deleteLayoutMut.mutate(layout.id)}
                    disabled={deleteLayoutMut.isPending}
                    aria-label={t('schedule.codes.delete_layout', { defaultValue: 'Delete layout' })}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {/* ── Result grid ────────────────────────────────────────────────── */}
      <GroupedGrid
        result={result}
        loading={runMut.isPending}
        expanded={expanded}
        onToggle={toggleGroup}
        page={page}
        pageSize={pageSize}
        onPageSize={(n) => {
          setPageSize(n);
        }}
        onPage={(p) => run(p, expanded)}
        dictName={dictName}
      />
    </div>
  );
}

/* ── Grouped grid renderer ────────────────────────────────────────────────── */

function GroupedGrid({
  result,
  loading,
  expanded,
  onToggle,
  page,
  pageSize,
  onPageSize,
  onPage,
  dictName,
}: {
  result: GroupedResponse | null;
  loading: boolean;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  page: number;
  pageSize: number;
  onPageSize: (n: number) => void;
  onPage: (p: number) => void;
  dictName: (id: string) => string;
}) {
  const { t } = useTranslation();

  if (loading && !result) {
    return (
      <Card padding="md" data-testid="codes-grouped-loading">
        <SkeletonTable rows={6} columns={4} />
      </Card>
    );
  }

  if (!result) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Layers size={28} strokeWidth={1.5} />}
          title={t('schedule.codes.grouped_empty', { defaultValue: 'Run a grouped view' })}
          description={t('schedule.codes.grouped_empty_desc', {
            defaultValue:
              'Pick one to three code dictionaries to group by, then run the query. The grid bands the activities by your chosen codes and pages through them server-side, so even a very large schedule stays responsive.',
          })}
        />
      </Card>
    );
  }

  // A band is visible only when its parent path is expanded (top level always
  // visible). A row is visible only when every ancestor band on its group_path
  // is expanded. Mirrors codes_bandtree.py path semantics.
  const isParentExpanded = (path: string[]): boolean => {
    if (path.length <= 1) return true;
    return expanded.has(pathId(path.slice(0, -1)));
  };
  const allAncestorsExpanded = (groupPath: string[]): boolean => {
    for (let i = 1; i <= groupPath.length; i++) {
      if (!expanded.has(pathId(groupPath.slice(0, i)))) return false;
    }
    return true;
  };

  const hasGroups = result.groups.length > 0;
  const totalPages = Math.max(1, Math.ceil(result.total_estimate / Math.max(1, pageSize)));

  // Interleave: render each visible band, and after a leaf-level band (or under
  // it) the rows whose group_path sits beneath it. To keep this simple and
  // robust against the page/band windowing, we render all visible bands first
  // (depth-first, already ordered), then the visible rows grouped under their
  // deepest expanded band.
  const visibleBands = result.groups.filter((b) => isParentExpanded(b.path));
  const visibleRows = result.rows.filter((r) =>
    hasGroups ? allAncestorsExpanded(r.group_path) : true,
  );

  return (
    <Card padding="none" data-testid="codes-grouped-result">
      <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-4 py-3">
        <h4 className="text-sm font-semibold text-content-primary">
          {t('schedule.codes.grouped_grid', { defaultValue: 'Grouped activities' })}
        </h4>
        <Badge variant="neutral" size="sm">
          {t('schedule.codes.total_count', {
            defaultValue: '{{count}} total',
            count: result.total_estimate,
          })}
        </Badge>
        {loading && <Loader2 size={14} className="animate-spin text-content-tertiary" />}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="px-3 py-2 text-left">
                {t('schedule.codes.col_activity', { defaultValue: 'Activity' })}
              </th>
              <th className="px-3 py-2 text-left">
                {t('schedule.codes.col_start', { defaultValue: 'Start' })}
              </th>
              <th className="px-3 py-2 text-left">
                {t('schedule.codes.col_end', { defaultValue: 'Finish' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('schedule.codes.col_duration', { defaultValue: 'Dur (d)' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('schedule.codes.col_progress', { defaultValue: 'Progress' })}
              </th>
              <th className="px-3 py-2 text-left">
                {t('schedule.codes.col_status', { defaultValue: 'Status' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('schedule.codes.col_float', { defaultValue: 'Float' })}
              </th>
              <th className="px-3 py-2 text-left">
                {t('schedule.codes.col_codes', { defaultValue: 'Codes' })}
              </th>
            </tr>
          </thead>
          <tbody data-testid="codes-grouped-body">
            {/* Bands */}
            {visibleBands.map((band) => {
              const id = pathId(band.path);
              const isOpen = expanded.has(id);
              const isNoneBand = band.key === GROUP_NONE_KEY;
              return (
                <tr key={`band-${id}`} className="border-t border-border-light bg-surface-secondary/40">
                  <td colSpan={8} className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => onToggle(id)}
                      aria-expanded={isOpen}
                      style={{ paddingLeft: `${band.depth * 18}px` }}
                      className="flex items-center gap-2 text-left"
                    >
                      {isOpen ? (
                        <ChevronDown size={14} className="shrink-0 text-content-tertiary" />
                      ) : (
                        <ChevronRight size={14} className="shrink-0 text-content-tertiary" />
                      )}
                      {band.color ? (
                        <span
                          className="inline-block h-3 w-3 shrink-0 rounded-sm"
                          style={{ backgroundColor: band.color }}
                        />
                      ) : null}
                      <span
                        className={`text-sm font-semibold ${
                          isNoneBand ? 'italic text-content-tertiary' : 'text-content-primary'
                        }`}
                      >
                        {band.label}
                      </span>
                      <Badge variant="neutral" size="sm">
                        {band.count}
                      </Badge>
                    </button>
                  </td>
                </tr>
              );
            })}

            {/* Leaf activity rows */}
            {visibleRows.length === 0 && visibleBands.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-sm text-content-tertiary">
                  {t('schedule.codes.no_rows', {
                    defaultValue: 'No activities match this grouping on this page.',
                  })}
                </td>
              </tr>
            ) : (
              visibleRows.map((r) => (
                <tr key={`row-${r.id}`} className="border-t border-border-light hover:bg-surface-secondary/30">
                  <td className="px-3 py-2">
                    <span
                      className="block min-w-0 truncate text-content-primary"
                      style={{ paddingLeft: `${(r.group_path.length + 1) * 18}px` }}
                    >
                      {r.name}
                      {r.is_critical && (
                        <Badge variant="error" size="sm">
                          {t('schedule.codes.critical', { defaultValue: 'Critical' })}
                        </Badge>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums text-content-secondary">
                    {r.start_date ?? '-'}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-content-secondary">
                    {r.end_date ?? '-'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.duration_days}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{Math.round(r.progress_pct)}%</td>
                  <td className="px-3 py-2">
                    <span className="text-xs text-content-secondary">{r.status}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.total_float ?? '-'}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {r.codes.map((c) => (
                        <span
                          key={`${c.dictionary_id}-${c.value_id}`}
                          title={dictName(c.dictionary_id)}
                          className="inline-flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary"
                        >
                          <span className="font-mono font-semibold">{c.code}</span>
                          {c.label && <span className="truncate">{c.label}</span>}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-light px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <span>
            {t('schedule.codes.page_of', {
              defaultValue: 'Page {{page}} of {{total}}',
              page,
              total: totalPages,
            })}
          </span>
          <label htmlFor="codes-page-size" className="ml-2">
            {t('schedule.codes.page_size', { defaultValue: 'Per page' })}
          </label>
          <select
            id="codes-page-size"
            value={pageSize}
            onChange={(e) => onPageSize(Number(e.target.value))}
            className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs"
          >
            {[50, 100, 200, 500].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPage(Math.max(1, page - 1))}
            disabled={loading || page <= 1}
          >
            {t('schedule.codes.prev', { defaultValue: 'Previous' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPage(page + 1)}
            disabled={loading || page >= totalPages}
          >
            {t('schedule.codes.next', { defaultValue: 'Next' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default ScheduleCodesPanel;
