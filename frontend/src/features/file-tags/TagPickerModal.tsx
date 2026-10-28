// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Modal that picks tags from the project's tag set + creates new ones.
 *
 * State model:
 *   - The picker is fully controlled — the parent passes the initial
 *     selection and gets the new selection on save. We never reach into
 *     hooks like `useAssignTag` from inside this modal because the same
 *     picker is reused both for single-file editing AND for bulk
 *     assignment (BulkTagDrawer) where the persistence rules differ.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Plus, Search } from 'lucide-react';
import clsx from 'clsx';
import { WideModal } from '@/shared/ui';
import { useCreateTag, useFileTags } from './hooks';
import type { TagCategory, TagRecord } from './types';

interface TagPickerModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Currently selected tag ids — used to pre-check pills in the list. */
  selectedTagIds: string[];
  /** Called with the new set of tag ids when the user clicks Save. */
  onSave: (tagIds: string[]) => void;
  /** Optional title override (e.g. "Tag 3 files"). */
  title?: string | undefined;
}

const CATEGORY_OPTIONS: { value: TagCategory; labelKey: string; defaultLabel: string }[] = [
  { value: 'discipline', labelKey: 'files.tags.category.discipline', defaultLabel: 'Discipline' },
  { value: 'phase', labelKey: 'files.tags.category.phase', defaultLabel: 'Phase' },
  { value: 'package', labelKey: 'files.tags.category.package', defaultLabel: 'Package' },
  { value: 'custom', labelKey: 'files.tags.category.custom', defaultLabel: 'Custom' },
];

const DEFAULT_TAG_COLORS = [
  '#3b82f6',
  '#ef4444',
  '#10b981',
  '#f59e0b',
  '#8b5cf6',
  '#ec4899',
  '#64748b',
];

export function TagPickerModal({
  open,
  onClose,
  projectId,
  selectedTagIds,
  onSave,
  title,
}: TagPickerModalProps) {
  const { t } = useTranslation();
  const tagsQuery = useFileTags(projectId);
  const createTag = useCreateTag();

  const [draftSelection, setDraftSelection] = useState<Set<string>>(
    new Set(selectedTagIds),
  );
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState<TagCategory>('custom');
  const [newColor, setNewColor] = useState<string>(DEFAULT_TAG_COLORS[0]!);

  // Re-sync when the modal reopens with a different initial selection.
  useEffect(() => {
    if (open) setDraftSelection(new Set(selectedTagIds));
  }, [open, selectedTagIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  const tags = tagsQuery.data ?? [];
  const filteredTags = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return tags;
    return tags.filter(
      (tag) =>
        tag.display_name.toLowerCase().includes(q) ||
        (tag.category ?? '').toLowerCase().includes(q),
    );
  }, [tags, filter]);

  const grouped = useMemo(() => groupTagsByCategory(filteredTags), [filteredTags]);

  function toggleTag(id: string) {
    setDraftSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    const created = await createTag.mutateAsync({
      project_id: projectId,
      display_name: newName.trim(),
      color: newColor,
      category: newCategory,
    });
    setDraftSelection((prev) => new Set(prev).add(created.id));
    setNewName('');
    setCreating(false);
  }

  function handleSave() {
    onSave(Array.from(draftSelection));
    onClose();
  }

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={
        title ??
        t('files.tags.picker_title', { defaultValue: 'Choose tags' })
      }
      size="md"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center h-9 px-3 text-sm font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="inline-flex items-center h-9 px-4 text-sm font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover"
          >
            {t('files.tags.save', { defaultValue: 'Save tags' })}
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        <div className="relative">
          <Search
            size={13}
            className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
          />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('files.tags.filter_placeholder', {
              defaultValue: 'Filter tags…',
            })}
            className="w-full h-9 ps-8 pe-3 text-sm rounded-lg border border-border-light bg-surface-primary text-content-primary placeholder:text-content-tertiary focus:outline-none focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
          />
        </div>

        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1">
              {category === 'uncategorized'
                ? t('files.tags.uncategorized', { defaultValue: 'Other' })
                : t(`files.tags.category.${category}`, { defaultValue: category })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {items.map((tag) => (
                <TagSelector
                  key={tag.id}
                  tag={tag}
                  selected={draftSelection.has(tag.id)}
                  onToggle={() => toggleTag(tag.id)}
                />
              ))}
            </div>
          </div>
        ))}

        {creating ? (
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3 space-y-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t('files.tags.new_name', { defaultValue: 'New tag name' })}
              className="w-full h-9 px-3 text-sm rounded-md border border-border-light bg-surface-primary"
            />
            <div className="flex items-center gap-2">
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value as TagCategory)}
                className="h-9 px-2 text-sm rounded-md border border-border-light bg-surface-primary"
              >
                {CATEGORY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey, { defaultValue: opt.defaultLabel })}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                {DEFAULT_TAG_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setNewColor(c)}
                    aria-label={`color ${c}`}
                    className={clsx(
                      'h-5 w-5 rounded-full border-2 transition-all',
                      newColor === c
                        ? 'border-content-primary scale-110'
                        : 'border-transparent',
                    )}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newName.trim() || createTag.isPending}
                className="ms-auto inline-flex items-center h-8 px-3 text-xs font-medium rounded-md bg-oe-blue text-white disabled:opacity-50"
              >
                {t('files.tags.create', { defaultValue: 'Create' })}
              </button>
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="inline-flex items-center h-8 px-3 text-xs rounded-md border border-border-light"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
            </div>
            {createTag.error && (
              <p className="text-2xs text-semantic-error">
                {createTag.error.message}
              </p>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1 text-sm text-oe-blue hover:underline"
          >
            <Plus size={13} />
            {t('files.tags.new_tag', { defaultValue: 'New tag…' })}
          </button>
        )}
      </div>
    </WideModal>
  );
}

function groupTagsByCategory(tags: TagRecord[]): Record<string, TagRecord[]> {
  const out: Record<string, TagRecord[]> = {};
  for (const tag of tags) {
    const key = tag.category ?? 'uncategorized';
    if (!out[key]) out[key] = [];
    out[key]!.push(tag);
  }
  return out;
}

interface TagSelectorProps {
  tag: TagRecord;
  selected: boolean;
  onToggle: () => void;
}

function TagSelector({ tag, selected, onToggle }: TagSelectorProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      className={clsx(
        'inline-flex items-center gap-1.5 h-7 px-2 rounded-md border text-xs font-medium transition-colors',
        selected
          ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
          : 'border-border-light text-content-secondary hover:bg-surface-secondary',
      )}
    >
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-full"
        style={{ backgroundColor: tag.color }}
      />
      <span className="truncate max-w-[160px]">{tag.display_name}</span>
      {selected && <Check size={11} />}
    </button>
  );
}
