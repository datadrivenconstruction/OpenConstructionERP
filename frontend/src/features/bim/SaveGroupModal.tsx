// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SaveGroupModal — turn the user's current viewer filter into a saved
 * `BIMElementGroup`.  Tiny modal: name + description + dynamic/static toggle.
 *
 * The actual filter criteria + element subset are passed in by the parent
 * (BIMPage) — this component is just the form.  Submit calls
 * `createElementGroup`, the backend resolves the membership and returns
 * a `BIMElementGroup` row that the parent caches.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Loader2, SlidersHorizontal } from 'lucide-react';
import {
  createElementGroup,
  resolveElementUUID,
  type BIMGroupFilterCriteria,
  type BIMElementGroup,
  type SmartViewGroup,
} from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { GROUP_COLORS } from './BIMGroupsPanel';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, isDemoReadOnlyRefusal } from '@/shared/lib/api';
import { Button } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import SmartViewBuilder from './SmartViewBuilder';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface SaveGroupModalProps {
  projectId: string;
  modelId: string | null;
  /** Filter criteria captured from the current state of BIMFilterPanel. */
  filterCriteria: BIMGroupFilterCriteria;
  /** Selected/visible element rows — used as a static snapshot when the
   *  user chooses "static" mode, ignored in dynamic mode.  Full rows
   *  (not just ids) so client-side stub ids (`_unmatched_N`) can be
   *  resolved to real BIMElement UUIDs before the group is persisted —
   *  storing stub ids verbatim makes the group unresolvable on reload. */
  elements: BIMElementData[];
  /** Live count of elements that match the filter right now — shown in
   *  the modal so the user knows how many things they're saving. */
  visibleCount: number;
  onClose: () => void;
  onSaved?: (group: BIMElementGroup) => void;
}

/** Bridge: convert the legacy chip-based filter_criteria into a Smart View
 *  rule tree so the advanced builder can open with the user's existing
 *  chips already populated. */
function legacyToTree(criteria: BIMGroupFilterCriteria): SmartViewGroup {
  const rules: SmartViewGroup['rules'] = [];
  const pushIn = (field: string, v: string | string[] | undefined) => {
    if (!v) return;
    const arr = Array.isArray(v) ? v : [v];
    if (arr.length === 0) return;
    if (arr.length === 1) {
      rules.push({ field, op: '=', value: arr[0]! });
    } else {
      rules.push({ field, op: 'in', value: arr });
    }
  };
  pushIn('element_type', criteria.element_type);
  pushIn('storey', criteria.storey);
  pushIn('discipline', criteria.discipline);
  pushIn('category', criteria.category);
  if (criteria.name_contains) {
    rules.push({ field: 'name', op: 'contains', value: criteria.name_contains });
  }
  if (criteria.property_filter) {
    for (const [k, v] of Object.entries(criteria.property_filter)) {
      if (v == null || v === '') continue;
      rules.push({ field: `properties.${k}`, op: '=', value: v });
    }
  }
  return { op: 'AND', rules };
}

export default function SaveGroupModal({
  projectId,
  modelId,
  filterCriteria,
  elements,
  visibleCount,
  onClose,
  onSaved,
}: SaveGroupModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  // Dynamic mode means "re-resolve from filter criteria every time".  If the
  // criteria are empty (e.g. the user only Ctrl+selected elements without
  // filtering), dynamic would resolve to *every* element in the project —
  // never what's wanted.  Default to static and disable dynamic in that case.
  const criteriaEmpty =
    !filterCriteria || Object.keys(filterCriteria).length === 0;
  const [isDynamic, setIsDynamic] = useState(false);
  const dynamicAllowed = !criteriaEmpty;
  const effectiveDynamic = isDynamic && dynamicAllowed;
  const [color, setColor] = useState('#2979ff');

  // Smart View advanced builder — opens with the user's current chip-based
  // filter pre-populated as a rule tree.  When the user has tweaked any
  // rule, ``ruleTree`` becomes the source of truth and the saved group's
  // filter_criteria carries ``rule_tree`` instead of the legacy keys.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const initialTree = useMemo(() => legacyToTree(filterCriteria), [filterCriteria]);
  const [ruleTree, setRuleTree] = useState<SmartViewGroup>(initialTree);
  const treeDirty = useMemo(
    () => JSON.stringify(ruleTree) !== JSON.stringify(initialTree),
    [ruleTree, initialTree],
  );

  const createMut = useMutation({
    mutationFn: async () => {
      // Static mode persists explicit element ids.  Resolve every
      // selected row to a real BIMElement UUID first — the viewer's
      // selection can carry client-side stub ids (`_unmatched_N`) or raw
      // Revit numeric ids for meshes the backend never materialised, and
      // storing those verbatim makes the group's members unresolvable on
      // reload (the long-standing "group save broken" bug). Dynamic mode
      // relies on filter criteria, so no id resolution is needed there.
      let resolvedIds: string[] | undefined;
      if (!effectiveDynamic) {
        resolvedIds = [];
        for (const el of elements) {
          if (!modelId) {
            // No active model — fall back to whatever id we have. Static
            // groups without a model are rare (cross-model selections).
            resolvedIds.push(el.id);
            continue;
          }
          resolvedIds.push(await resolveElementUUID(modelId, el));
        }
      }
      // When the advanced rule tree has been edited, send it as the
      // canonical predicate.  Legacy chip-based filter_criteria are
      // retained for backward compatibility with older list views.
      const effectiveCriteria: BIMGroupFilterCriteria & {
        rule_tree?: SmartViewGroup;
      } = { ...filterCriteria };
      if (treeDirty || advancedOpen) {
        effectiveCriteria.rule_tree = ruleTree;
      }
      return createElementGroup(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        model_id: modelId,
        is_dynamic: effectiveDynamic,
        filter_criteria: effectiveCriteria,
        element_ids: resolvedIds,
        color,
      });
    },
    onSuccess: (group) => {
      addToast({
        type: 'success',
        title: t('bim.group_saved_title', { defaultValue: 'Group saved' }),
        message: t('bim.group_saved_msg', {
          defaultValue: '"{{name}}" - {{count}} elements',
          name: group.name,
          count: group.element_count,
        }),
      });
      qc.invalidateQueries({
        predicate: (q) => {
          const k = q.queryKey;
          return Array.isArray(k) && k[0] === 'bim-element-groups' && k[1] === projectId;
        },
      });
      onSaved?.(group);
      onClose();
    },
    onError: (err: Error) => {
      // The public demo refuses every write; say what still works instead
      // of a bare error, and close so ad hoc grouping stays in reach.
      if (err instanceof ApiError && isDemoReadOnlyRefusal(err.status, err.body)) {
        addToast({
          type: 'info',
          title: t('bim.save_as_group', { defaultValue: 'Save as group' }),
          message: t('bim.groups_save_demo', {
            defaultValue:
              'Saved groups are not kept on the public demo. Grouping and filters still work here; install the platform to save groups.',
          }),
        });
        onClose();
        return;
      }
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  const canSave = name.trim().length > 0 && !createMut.isPending;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bim.save_group_title', {
        defaultValue: 'Save current filter as group',
      })}
      size="md"
      busy={createMut.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={createMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            disabled={!canSave}
            icon={
              createMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )
            }
          >
            {t('bim.save_group', { defaultValue: 'Save group' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('bim.group_name', { defaultValue: 'Group name' })}
          required
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('bim.group_name_placeholder', {
              defaultValue: 'e.g. Walls on Level 1',
            })}
            className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
        </WideModalField>

        <WideModalField
          label={t('bim.group_description', {
            defaultValue: 'Description (optional)',
          })}
        >
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue resize-none"
          />
        </WideModalField>

        <WideModalField
          label={t('bim.group_color', { defaultValue: 'Color' })}
        >
          <div className="flex items-center gap-1.5">
            {GROUP_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                className={`h-6 w-6 rounded-full border-2 transition-transform hover:scale-110 ${
                  color === c
                    ? 'border-content-primary scale-105'
                    : 'border-transparent'
                }`}
                style={{ background: c }}
                title={c}
              />
            ))}
          </div>
        </WideModalField>

        {/* Dynamic vs static toggle */}
        <div className="rounded-md border border-border-light p-3 space-y-2">
          <label
            className={`flex items-start gap-2 ${
              dynamicAllowed ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'
            }`}
            title={
              dynamicAllowed
                ? undefined
                : t('bim.group_dynamic_disabled_title', {
                    defaultValue:
                      'Dynamic mode needs at least one filter (storey, type, or search). Apply a filter to enable it.',
                  })
            }
          >
            <input
              type="radio"
              checked={effectiveDynamic}
              onChange={() => setIsDynamic(true)}
              disabled={!dynamicAllowed}
              className="mt-0.5"
            />
            <div className="text-xs">
              <div className="font-semibold text-content-primary">
                {t('bim.group_dynamic', { defaultValue: 'Dynamic' })}
              </div>
              <div className="text-content-tertiary text-[11px]">
                {dynamicAllowed
                  ? t('bim.group_dynamic_desc', {
                      defaultValue:
                        'Re-compute members from the filter every time. Auto-updates when the model is re-imported.',
                    })
                  : t('bim.group_dynamic_desc_disabled', {
                      defaultValue:
                        'Disabled - no filter is active. Apply a storey, type or search filter to enable dynamic mode.',
                    })}
              </div>
            </div>
          </label>
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              checked={!effectiveDynamic}
              onChange={() => setIsDynamic(false)}
              className="mt-0.5"
            />
            <div className="text-xs">
              <div className="font-semibold text-content-primary">
                {t('bim.group_static', { defaultValue: 'Static' })}
              </div>
              <div className="text-content-tertiary text-[11px]">
                {t('bim.group_static_desc', {
                  defaultValue:
                    'Snapshot the current {{count}} elements. Membership stays frozen even if the model changes.',
                  count: elements.length,
                })}
              </div>
            </div>
          </label>
        </div>

        {/* Advanced rule builder — toggled disclosure so the modal stays
            compact for the common chip-based case but exposes the full
            canonical-format-aware builder for power users.  When opened
            and edited, the rule tree becomes the source of truth for the
            saved group's filter_criteria. */}
        <div className="rounded-md border border-border-light">
          <button
            type="button"
            onClick={() => setAdvancedOpen((v) => !v)}
            className="w-full flex items-center justify-between gap-2 px-3 py-2"
          >
            <span className="flex items-center gap-1.5 text-xs font-semibold text-content-primary">
              <SlidersHorizontal size={12} className="text-oe-blue" />
              {t('bim.smartview.advanced_title', {
                defaultValue: 'Smart View - advanced rules',
              })}
              {treeDirty && (
                <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                  {t('bim.smartview.edited', { defaultValue: 'edited' })}
                </span>
              )}
            </span>
            <span className="text-[10px] text-content-tertiary">
              {advancedOpen
                ? t('common.collapse', { defaultValue: 'Collapse' })
                : t('common.expand', { defaultValue: 'Expand' })}
            </span>
          </button>
          {advancedOpen && (
            <div className="px-3 pb-3 border-t border-border-light pt-3">
              <SmartViewBuilder
                modelId={modelId}
                projectId={projectId}
                value={ruleTree}
                onChange={setRuleTree}
              />
            </div>
          )}
        </div>

        {/* Counts pill — show what will actually be saved */}
        <div className="flex items-center gap-2 text-[11px] text-content-tertiary">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-oe-blue/10 text-oe-blue font-medium">
            {(effectiveDynamic ? visibleCount : elements.length).toLocaleString(getNumberLocale())}{' '}
            {t('bim.elements', { defaultValue: 'elements' })}
          </span>
          {modelId && (
            <span>{t('bim.in_current_model', { defaultValue: 'in this model' })}</span>
          )}
        </div>
      </WideModalSection>
    </WideModal>
  );
}
