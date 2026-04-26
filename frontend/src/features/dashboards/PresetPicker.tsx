/**
 * PresetPicker (T05) — choose / save dashboards.
 *
 * Dropdown that surfaces the caller's "My presets" + every "Shared
 * collection" available on the current project. The "Save current
 * as preset…" action opens a modal that captures (name, description,
 * kind) and posts the current dashboard state via the supplied
 * ``snapshot()`` callback.
 *
 * Wired into :class:`QuickInsightPanel` via the ``onPinChart`` prop —
 * the previous "no T05 yet" toast becomes a real save.
 */
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bookmark, Check, Plus, Users } from 'lucide-react';

import { Button, Card, EmptyState, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import {
  createDashboardPreset,
  listDashboardPresets,
  type CreateDashboardPresetInput,
  type DashboardPreset,
} from './api';

export interface PresetPickerProps {
  projectId?: string | null;
  /**
   * Snapshot of the current dashboard state. Lazily evaluated when the
   * user triggers "Save as preset" so we only walk the chart/filter
   * stores when the user actually wants to save.
   */
  snapshot: () => Record<string, unknown>;
  /** Optional: load a previously-saved preset back into the dashboard. */
  onSelect?: (preset: DashboardPreset) => void;
}

export function PresetPicker({ projectId, snapshot, onSelect }: PresetPickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);

  const presetsQuery = useQuery({
    queryKey: ['dashboard-presets', projectId ?? null],
    queryFn: () =>
      listDashboardPresets({
        projectId: projectId ?? undefined,
      }),
    staleTime: 30 * 1000,
    enabled: open || showSaveModal,
  });

  const myPresets = useMemo(() => {
    return (presetsQuery.data?.items ?? []).filter(
      (p) => p.kind === 'preset',
    );
  }, [presetsQuery.data]);

  const collections = useMemo(() => {
    return (presetsQuery.data?.items ?? []).filter(
      (p) => p.kind === 'collection',
    );
  }, [presetsQuery.data]);

  const handleSelect = useCallback(
    (preset: DashboardPreset) => {
      onSelect?.(preset);
      setOpen(false);
    },
    [onSelect],
  );

  return (
    <div className="relative inline-block" data-testid="preset-picker">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        data-testid="preset-picker-trigger"
      >
        <Bookmark className="mr-1 h-3 w-3" />
        {t('dashboards.presets_button', { defaultValue: 'Presets' })}
      </Button>

      {open && (
        <div
          className="absolute right-0 z-30 mt-1 w-72 rounded border border-border-light bg-surface-primary shadow-lg"
          data-testid="preset-picker-dropdown"
          role="menu"
        >
          {presetsQuery.isLoading && (
            <div className="p-3 text-xs text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}

          {!presetsQuery.isLoading && (
            <>
              <PresetGroup
                title={t('dashboards.my_presets', {
                  defaultValue: 'My presets',
                })}
                presets={myPresets}
                onSelect={handleSelect}
                emptyHint={t('dashboards.no_presets', {
                  defaultValue: 'No saved presets yet.',
                })}
                testIdPrefix="my-preset"
              />
              <PresetGroup
                title={t('dashboards.shared_collections', {
                  defaultValue: 'Shared collections',
                })}
                presets={collections}
                onSelect={handleSelect}
                icon={<Users className="h-3 w-3" />}
                emptyHint={t('dashboards.no_collections', {
                  defaultValue: 'No shared collections on this project yet.',
                })}
                testIdPrefix="shared-collection"
              />
            </>
          )}

          <div className="border-t border-border-light p-1.5">
            <button
              type="button"
              onClick={() => {
                setShowSaveModal(true);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs text-oe-blue hover:bg-surface-secondary"
              data-testid="preset-picker-save-current"
            >
              <Plus className="h-3 w-3" />
              {t('dashboards.save_current_as_preset', {
                defaultValue: 'Save current as preset…',
              })}
            </button>
          </div>
        </div>
      )}

      {showSaveModal && (
        <PresetSaveModal
          projectId={projectId ?? null}
          snapshot={snapshot}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </div>
  );
}

interface PresetGroupProps {
  title: string;
  presets: DashboardPreset[];
  onSelect: (p: DashboardPreset) => void;
  emptyHint: string;
  icon?: React.ReactNode;
  testIdPrefix: string;
}

function PresetGroup({
  title,
  presets,
  onSelect,
  emptyHint,
  icon,
  testIdPrefix,
}: PresetGroupProps) {
  return (
    <div className="border-b border-border-light p-1.5 last:border-b-0">
      <div className="flex items-center gap-1 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
        {icon}
        {title}
      </div>
      {presets.length === 0 ? (
        <div className="px-2 py-1 text-xs text-content-tertiary">
          {emptyHint}
        </div>
      ) : (
        <ul role="none" data-testid={`${testIdPrefix}-list`}>
          {presets.map((p) => (
            <li key={p.id} role="none">
              <button
                type="button"
                role="menuitem"
                onClick={() => onSelect(p)}
                data-testid={`${testIdPrefix}-${p.id}`}
                className="flex w-full items-start gap-2 rounded px-2 py-1 text-left hover:bg-surface-secondary"
              >
                <Check className="mt-0.5 h-3 w-3 opacity-0 group-hover:opacity-100" />
                <span className="flex-1">
                  <span className="block text-xs font-medium text-content-primary">
                    {p.name}
                  </span>
                  {p.description && (
                    <span className="block text-[10px] text-content-tertiary">
                      {p.description}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Save modal ─────────────────────────────────────────────────────────── */

interface PresetSaveModalProps {
  projectId: string | null;
  snapshot: () => Record<string, unknown>;
  onClose: () => void;
}

export function PresetSaveModal({
  projectId,
  snapshot,
  onClose,
}: PresetSaveModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [kind, setKind] = useState<'preset' | 'collection'>('preset');
  const [shared, setShared] = useState(false);

  const mutation = useMutation({
    mutationFn: (input: CreateDashboardPresetInput) =>
      createDashboardPreset(input),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['dashboard-presets', projectId ?? null],
      });
      toast({
        type: 'success',
        title: t('dashboards.preset_saved_title', {
          defaultValue: 'Preset saved',
        }),
        message: t('dashboards.preset_saved_msg', {
          defaultValue: 'Available from the Presets dropdown.',
        }),
      });
      onClose();
    },
    onError: (err: Error) => {
      toast({
        type: 'error',
        title: t('dashboards.preset_save_failed', {
          defaultValue: 'Could not save preset',
        }),
        message: err.message,
      });
    },
  });

  const canSubmit = name.trim().length > 0 && !mutation.isPending;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSubmit) return;
      mutation.mutate({
        name: name.trim(),
        description: description.trim() || null,
        kind: shared ? 'collection' : kind,
        project_id: projectId ?? null,
        config_json: snapshot(),
        shared_with_project: shared,
      });
    },
    [canSubmit, name, description, kind, shared, projectId, snapshot, mutation],
  );

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      data-testid="preset-save-modal"
    >
      <Card className="w-[420px] max-w-[95vw] p-0">
        <form onSubmit={handleSubmit}>
          <div className="border-b border-border-light px-4 py-3">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboards.save_preset_title', {
                defaultValue: 'Save current dashboard',
              })}
            </h3>
          </div>
          <div className="space-y-3 p-4">
            <div>
              <label
                htmlFor="preset-name"
                className="block text-xs font-medium text-content-secondary"
              >
                {t('dashboards.preset_name', { defaultValue: 'Name' })}
              </label>
              <Input
                id="preset-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                autoFocus
                data-testid="preset-save-name"
              />
            </div>
            <div>
              <label
                htmlFor="preset-description"
                className="block text-xs font-medium text-content-secondary"
              >
                {t('dashboards.preset_description', {
                  defaultValue: 'Description',
                })}
              </label>
              <Input
                id="preset-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={2000}
                data-testid="preset-save-description"
              />
            </div>
            <fieldset>
              <legend className="text-xs font-medium text-content-secondary">
                {t('dashboards.preset_visibility', {
                  defaultValue: 'Visibility',
                })}
              </legend>
              <div className="mt-1 flex items-center gap-3 text-xs">
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="preset-kind"
                    checked={!shared}
                    onChange={() => {
                      setShared(false);
                      setKind('preset');
                    }}
                    data-testid="preset-save-kind-private"
                  />
                  {t('dashboards.preset_private', {
                    defaultValue: 'Private preset',
                  })}
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="preset-kind"
                    checked={shared}
                    onChange={() => {
                      setShared(true);
                      setKind('collection');
                    }}
                    data-testid="preset-save-kind-shared"
                  />
                  {t('dashboards.preset_shared', {
                    defaultValue: 'Shared collection (project-wide)',
                  })}
                </label>
              </div>
            </fieldset>
          </div>
          <div className="flex justify-end gap-2 border-t border-border-light px-4 py-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClose}
              data-testid="preset-save-cancel"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={!canSubmit}
              data-testid="preset-save-submit"
            >
              {mutation.isPending
                ? t('common.saving', { defaultValue: 'Saving…' })
                : t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

/**
 * Empty-state helper for places that want to render the picker
 * even when there are no presets yet — keeps the "Save current as preset"
 * affordance visible.
 */
export function PresetPickerEmptyState() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<Bookmark className="h-8 w-8 text-neutral-500" />}
      title={t('dashboards.no_presets_title', {
        defaultValue: 'No saved presets',
      })}
      description={t('dashboards.no_presets_desc', {
        defaultValue:
          'Pin a chart from Quick Insights to start a preset, or save the current view.',
      })}
    />
  );
}
