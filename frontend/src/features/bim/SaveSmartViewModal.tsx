// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SaveSmartViewModal — dedicated save modal for the Smart View builder.
 *
 * Unlike the older ``SaveGroupModal`` (which doubles as a chip-based
 * filter saver), this modal is rule-tree-first:
 *   - name + description (required name)
 *   - color tag (eight presets reused from BIMGroupsPanel)
 *   - "share with team" toggle (private vs project-wide)
 *   - "default for this module" toggle (auto-applies when the user
 *     opens the BIM module without an explicit selection)
 *
 * The rule tree itself is passed in by the parent (the SmartViewBuilder
 * holds it); this modal just decorates and persists.  Persistence reuses
 * the existing ``createElementGroup`` endpoint with ``is_dynamic=true``
 * and ``filter_criteria.rule_tree`` carrying the canonical predicate.
 *
 * Sharing + default flags are stored on the group's ``metadata`` blob
 * (no schema migration needed) — the backend already accepts arbitrary
 * JSON in that column.  When the user-only mode is selected we also
 * stamp ``metadata.private_to`` with the current user id so the
 * groups list can client-filter.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Save, Share2, Star } from 'lucide-react';
import {
  createElementGroup,
  type BIMElementGroup,
  type SmartViewGroup,
} from './api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { Button } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { GROUP_COLORS } from './BIMGroupsPanel';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export interface SaveSmartViewModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  modelId: string | null;
  /** The rule tree the builder has assembled — saved as
   *  ``filter_criteria.rule_tree`` so loading the group re-hydrates the
   *  builder with the same predicate. */
  ruleTree: SmartViewGroup;
  /** Current live count from the preview pill, shown in the modal so
   *  the user knows how many elements they're saving. */
  matchedCount: number;
  /** Optional pre-fill (used when editing rather than creating). */
  defaults?: {
    name?: string;
    description?: string;
    color?: string;
    shareWithTeam?: boolean;
    defaultForModule?: boolean;
  };
  onSaved?: (group: BIMElementGroup) => void;
}

export default function SaveSmartViewModal({
  open,
  onClose,
  projectId,
  modelId,
  ruleTree,
  matchedCount,
  defaults,
  onSaved,
}: SaveSmartViewModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userId = useAuthStore((s) => s.userEmail ?? null);

  const [name, setName] = useState(defaults?.name ?? '');
  const [description, setDescription] = useState(defaults?.description ?? '');
  const [color, setColor] = useState(defaults?.color ?? GROUP_COLORS[0]!);
  const [shareWithTeam, setShareWithTeam] = useState(
    defaults?.shareWithTeam ?? true,
  );
  const [defaultForModule, setDefaultForModule] = useState(
    defaults?.defaultForModule ?? false,
  );

  const createMut = useMutation({
    mutationFn: async () => {
      // ``metadata`` is accepted by the backend create endpoint (it's a
      // JSONB column on BIMElementGroup) but isn't on
      // ``BIMElementGroupCreate``'s TS surface — extend locally so we
      // don't have to widen the shared type.  Likewise rule_tree on
      // filter_criteria is an OE extension; we tunnel it under an
      // intersection type.
      const metadata: Record<string, unknown> = {
        kind: 'smart_view',
        default_for_module: defaultForModule,
      };
      if (!shareWithTeam && userId) metadata.private_to = userId;
      type ExtendedCriteria = Parameters<typeof createElementGroup>[1]['filter_criteria'] & {
        rule_tree?: SmartViewGroup;
      };
      const filter_criteria: ExtendedCriteria = { rule_tree: ruleTree };
      type ExtendedPayload = Parameters<typeof createElementGroup>[1] & {
        metadata?: Record<string, unknown>;
      };
      const payload: ExtendedPayload = {
        name: name.trim(),
        description: description.trim() || undefined,
        model_id: modelId,
        is_dynamic: true,
        filter_criteria,
        color,
        metadata,
      };
      return createElementGroup(projectId, payload);
    },
    onSuccess: (group) => {
      addToast({
        type: 'success',
        title: t('bim.smartview.saved_title', {
          defaultValue: 'Smart View saved',
        }),
        message: t('bim.smartview.saved_msg', {
          defaultValue: '"{{name}}" - {{count}} elements',
          name: group.name,
          count: group.element_count,
        }),
      });
      qc.invalidateQueries({
        predicate: (q) => {
          const k = q.queryKey;
          return (
            Array.isArray(k) && k[0] === 'bim-element-groups' && k[1] === projectId
          );
        },
      });
      onSaved?.(group);
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  const canSave = name.trim().length > 0 && !createMut.isPending;
  if (!open) return null;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bim.smartview.save_title', {
        defaultValue: 'Save as Smart View',
      })}
      subtitle={t('bim.smartview.save_subtitle', {
        defaultValue:
          'Pin this rule tree so the team can re-apply it with one click.',
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
            {t('bim.smartview.save_btn', { defaultValue: 'Save Smart View' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('bim.smartview.field_name', { defaultValue: 'Name' })}
          required
        >
          <input
            type="text"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('bim.smartview.name_placeholder', {
              defaultValue: 'e.g. Concrete walls above level 2',
            })}
            className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
        </WideModalField>

        <WideModalField
          label={t('bim.smartview.field_description', {
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
          label={t('bim.smartview.field_color', {
            defaultValue: 'Color / tag',
          })}
        >
          <div
            className="flex items-center gap-1.5"
            role="radiogroup"
            aria-label={t('bim.smartview.field_color', {
              defaultValue: 'Color / tag',
            })}
          >
            {GROUP_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={color === c}
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

        {/* Share + default toggles */}
        <div className="rounded-md border border-border-light p-3 space-y-2">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={shareWithTeam}
              onChange={(e) => setShareWithTeam(e.target.checked)}
              className="mt-0.5"
            />
            <div className="text-xs flex-1">
              <div className="font-semibold text-content-primary flex items-center gap-1.5">
                <Share2 size={11} className="text-oe-blue" />
                {t('bim.smartview.share_label', {
                  defaultValue: 'Share with team',
                })}
              </div>
              <div className="text-content-tertiary text-[11px]">
                {t('bim.smartview.share_desc', {
                  defaultValue:
                    'Anyone with access to this project can see and apply it. Uncheck to keep it private to you.',
                })}
              </div>
            </div>
          </label>
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={defaultForModule}
              onChange={(e) => setDefaultForModule(e.target.checked)}
              className="mt-0.5"
            />
            <div className="text-xs flex-1">
              <div className="font-semibold text-content-primary flex items-center gap-1.5">
                <Star size={11} className="text-amber-500" />
                {t('bim.smartview.default_label', {
                  defaultValue: 'Default for BIM module',
                })}
              </div>
              <div className="text-content-tertiary text-[11px]">
                {t('bim.smartview.default_desc', {
                  defaultValue:
                    'Auto-apply this view when the BIM page opens with no explicit selection.',
                })}
              </div>
            </div>
          </label>
        </div>

        {/* Match-count summary */}
        <div className="flex items-center gap-2 text-[11px] text-content-tertiary">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-oe-blue/10 text-oe-blue font-medium">
            {matchedCount.toLocaleString(getNumberLocale())}{' '}
            {t('bim.elements', { defaultValue: 'elements' })}
          </span>
          <span>
            {t('bim.smartview.will_be_saved', {
              defaultValue: 'will be saved as the initial snapshot',
            })}
          </span>
        </div>
      </WideModalSection>
    </WideModal>
  );
}
