// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clash Profile Manager — item #23.
 *
 * Route: /clash/profiles  (project chosen via the global selector or a
 * legacy ?project= deep-link, mirroring ClashDetectionPage).
 *
 * A *profile* is a reusable, named clash-run configuration template per
 * project: tolerance, clearance, mode, discipline filter, selection sets,
 * per-discipline-pair rules and the smart-issue spatial grid — everything
 * a coordinator tunes, minus the model selection. The page is a two-pane
 * library: a list of profile cards on the left, a detail / edit panel on
 * the right, plus an Apply modal that launches a fresh run from a profile.
 *
 * AI-free, deterministic: a profile is plain config the user authors and
 * confirms; applying it just creates a normal clash run.
 */

import { useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Layers,
  Plus,
  Pencil,
  Trash2,
  Play,
  Save,
  X,
  Copy,
  Radar,
  FolderOpen,
  Loader2,
  SlidersHorizontal,
} from 'lucide-react';
import { Card } from '@/shared/ui/Card';
import { Button } from '@/shared/ui/Button';
import { Badge } from '@/shared/ui/Badge';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { PageHeader } from '@/shared/ui/PageHeader';
import { EmptyState } from '@/shared/ui/EmptyState';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import {
  clashApi,
  type ClashProfile,
  type ClashProfileCreateBody,
  type ClashType,
} from './api';

const CLASH_TYPES: ClashType[] = ['both', 'hard', 'clearance'];
const MODES = ['cross_discipline', 'all', 'selected', 'selection_sets'];

/** Editable form state — the subset of profile fields this page exposes.
 *  Selection sets / discipline filter / rules are preserved verbatim from
 *  the loaded profile (this page never strips them) but are not edited
 *  here; they are authored from the run-config form on /clash. */
interface ProfileForm {
  name: string;
  description: string;
  clash_type: ClashType;
  ignore_same_model: boolean;
  toleranceMm: number;
  clearanceMm: number;
  mode: string;
  spatial_grid_mm: number;
}

function profileToForm(p: ClashProfile): ProfileForm {
  return {
    name: p.name,
    description: p.description ?? '',
    clash_type: p.clash_type,
    ignore_same_model: p.ignore_same_model,
    toleranceMm: Math.round(p.tolerance_m * 1000),
    clearanceMm: Math.round(p.clearance_m * 1000),
    mode: p.mode,
    spatial_grid_mm: p.spatial_grid_mm,
  };
}

function blankForm(): ProfileForm {
  return {
    name: '',
    description: '',
    clash_type: 'both',
    ignore_same_model: false,
    toleranceMm: 10,
    clearanceMm: 0,
    mode: 'cross_discipline',
    spatial_grid_mm: 500,
  };
}

/** Build the create/update body from the form + a source profile (so the
 *  non-edited config fields — selection sets, discipline filter, rules —
 *  ride along unchanged on an update or duplicate). */
function formToBody(
  form: ProfileForm,
  source?: ClashProfile,
): ClashProfileCreateBody {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    clash_type: form.clash_type,
    ignore_same_model: form.ignore_same_model,
    tolerance_m: form.toleranceMm / 1000,
    clearance_m: form.clearanceMm / 1000,
    mode: form.mode,
    spatial_grid_mm: form.spatial_grid_mm,
    discipline_filter: source?.discipline_filter ?? null,
    set_a: source?.set_a ?? null,
    set_b: source?.set_b ?? null,
    rules: source?.rules ?? [],
  };
}

export default function ClashProfileManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const ctxProjectId = useActiveProjectId();
  const ctxProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = ctxProjectId ?? params.get('project') ?? '';

  const [selectedId, setSelectedId] = useState<string | null>(null);
  // null = not editing; an object = the edit/create form is open. When
  // `creatingNew` the form has no source profile.
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);
  // The profile being applied (Apply modal open when non-null).
  const [applyTarget, setApplyTarget] = useState<ClashProfile | null>(null);

  const profilesQuery = useQuery({
    queryKey: ['clash-profiles', projectId],
    queryFn: () => clashApi.listProfiles(projectId),
    enabled: !!projectId,
  });

  const profiles = profilesQuery.data ?? [];
  const selected = useMemo(
    () => profiles.find((p) => p.id === selectedId) ?? null,
    [profiles, selectedId],
  );

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['clash-profiles', projectId] });
  }, [qc, projectId]);

  const createMut = useMutation({
    mutationFn: (body: ClashProfileCreateBody) =>
      clashApi.createProfile(projectId, body),
    onSuccess: (created) => {
      addToast({
        type: 'success',
        title: t('clash.profiles.created', {
          defaultValue: 'Profile saved',
        }),
      });
      invalidate();
      setSelectedId(created.id);
      setForm(null);
      setCreatingNew(false);
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: ClashProfileCreateBody }) =>
      clashApi.updateProfile(projectId, id, body),
    onSuccess: (updated) => {
      addToast({
        type: 'success',
        title: t('clash.profiles.updated', {
          defaultValue: 'Profile updated',
        }),
      });
      invalidate();
      setSelectedId(updated.id);
      setForm(null);
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => clashApi.deleteProfile(projectId, id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('clash.profiles.deleted', {
          defaultValue: 'Profile deleted',
        }),
      });
      invalidate();
      setSelectedId(null);
      setForm(null);
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const startCreate = useCallback(() => {
    setForm(blankForm());
    setCreatingNew(true);
    setSelectedId(null);
  }, []);

  const startEdit = useCallback((p: ClashProfile) => {
    setForm(profileToForm(p));
    setCreatingNew(false);
    setSelectedId(p.id);
  }, []);

  const startDuplicate = useCallback(
    (p: ClashProfile) => {
      const f = profileToForm(p);
      f.name = t('clash.profiles.copyName', {
        defaultValue: '{{name}} (copy)',
        name: p.name,
      });
      setForm(f);
      setCreatingNew(true);
      setSelectedId(null);
    },
    [t],
  );

  const handleSave = useCallback(() => {
    if (!form) return;
    if (!form.name.trim()) {
      addToast({
        type: 'error',
        title: t('clash.profiles.nameRequired', {
          defaultValue: 'A profile name is required',
        }),
      });
      return;
    }
    if (creatingNew) {
      // Duplicate carries the source profile's selection sets / rules; a
      // brand-new profile starts with none.
      const source = selected ?? undefined;
      createMut.mutate(formToBody(form, source));
    } else if (selected) {
      updateMut.mutate({ id: selected.id, body: formToBody(form, selected) });
    }
  }, [form, creatingNew, selected, createMut, updateMut, addToast, t]);

  const handleDelete = useCallback(
    async (p: ClashProfile) => {
      const ok = await confirm({
        title: t('clash.profiles.deleteTitle', {
          defaultValue: 'Delete profile?',
        }),
        message: t('clash.profiles.deleteMessage', {
          defaultValue:
            'Delete the profile "{{name}}"? Existing runs are not affected.',
          name: p.name,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(p.id);
    },
    [confirm, deleteMut, t],
  );

  if (!projectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb
          items={[
            { label: t('clash.profiles.title', { defaultValue: 'Clash Profiles' }) },
          ]}
        />
        <EmptyState
          icon={<FolderOpen className="w-8 h-8" />}
          title={t('clash.profiles.noProject', {
            defaultValue: 'Select a project',
          })}
          description={t('clash.profiles.noProjectHint', {
            defaultValue:
              'Choose a project from the selector to manage its clash profiles.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Canonical top block (MODULE_STYLE_GUIDE.md §2): Breadcrumb then the
          shared PageHeader. The module name + icon live in the global top
          app bar, so there is no in-page H1 - PageHeader carries the
          subtitle and actions, with srTitle for screen readers. */}
      <Breadcrumb
        items={[
          ...(ctxProjectName
            ? [{ label: ctxProjectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('clash.profiles.title', { defaultValue: 'Clash Profiles' }) },
        ]}
      />
      <PageHeader
        srTitle={t('clash.profiles.title', { defaultValue: 'Clash Profiles' })}
        subtitle={t('clash.profiles.subtitle', {
          defaultValue:
            'Reusable clash-run configurations you can launch on any model set.',
        })}
        actions={
          <>
            <Link to={`/clash${ctxProjectId ? '' : `?project=${projectId}`}`}>
              <Button variant="secondary" size="sm" icon={<Radar className="w-4 h-4" />}>
                {t('clash.profiles.backToClash', {
                  defaultValue: 'Clash detection',
                })}
              </Button>
            </Link>
            <Button size="sm" icon={<Plus className="w-4 h-4" />} onClick={startCreate}>
              {t('clash.profiles.new', { defaultValue: 'New profile' })}
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-5">
        {/* Profile list */}
        <div className="space-y-2">
          {profilesQuery.isLoading && (
            <div className="flex items-center gap-2 text-sm text-content-tertiary py-4">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}
          {!profilesQuery.isLoading && profiles.length === 0 && (
            <Card padding="none" className="p-4">
              <EmptyState
                icon={<Layers className="w-7 h-7" />}
                title={t('clash.profiles.emptyTitle', {
                  defaultValue: 'No profiles yet',
                })}
                description={t('clash.profiles.emptyHint', {
                  defaultValue:
                    'Save a clash-run configuration as a profile to reuse it later.',
                })}
              />
            </Card>
          )}
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setSelectedId(p.id);
                setForm(null);
              }}
              className={clsx(
                'w-full text-left rounded-xl border px-3.5 py-3 transition-colors',
                selectedId === p.id && !form
                  ? 'border-oe-blue bg-oe-blue/5'
                  : 'border-border-subtle hover:border-border-strong bg-surface-1',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-content-primary truncate">
                  {p.name}
                </span>
                <Badge variant="neutral" size="sm">
                  {p.mode === 'selection_sets'
                    ? t('clash.profiles.modeSets', { defaultValue: 'Sets' })
                    : p.mode}
                </Badge>
              </div>
              {p.description && (
                <p className="text-xs text-content-tertiary mt-1 line-clamp-2">
                  {p.description}
                </p>
              )}
              <div className="flex items-center gap-3 mt-2 text-[11px] text-content-tertiary">
                <span>
                  {t('clash.profiles.toleranceShort', {
                    defaultValue: 'tol {{mm}} mm',
                    mm: Math.round(p.tolerance_m * 1000),
                  })}
                </span>
                {p.rules.length > 0 && (
                  <span>
                    {t('clash.profiles.ruleCount', {
                      defaultValue: '{{count}} rules',
                      count: p.rules.length,
                    })}
                  </span>
                )}
                <span className="ml-auto">
                  <DateDisplay value={p.created_at} />
                </span>
              </div>
            </button>
          ))}
        </div>

        {/* Detail / edit panel */}
        <div>
          {form ? (
            <ProfileEditor
              form={form}
              setForm={setForm}
              creating={creatingNew}
              saving={createMut.isPending || updateMut.isPending}
              onSave={handleSave}
              onCancel={() => {
                setForm(null);
                setCreatingNew(false);
              }}
            />
          ) : selected ? (
            <ProfileDetail
              profile={selected}
              onEdit={() => startEdit(selected)}
              onDuplicate={() => startDuplicate(selected)}
              onDelete={() => void handleDelete(selected)}
              onApply={() => setApplyTarget(selected)}
            />
          ) : (
            <Card padding="none" className="p-6">
              <EmptyState
                icon={<SlidersHorizontal className="w-7 h-7" />}
                title={t('clash.profiles.selectTitle', {
                  defaultValue: 'Select a profile',
                })}
                description={t('clash.profiles.selectHint', {
                  defaultValue:
                    'Pick a profile from the list to view, edit or launch it - or create a new one.',
                })}
              />
            </Card>
          )}
        </div>
      </div>

      {applyTarget && (
        <ApplyModal
          projectId={projectId}
          profile={applyTarget}
          onClose={() => setApplyTarget(null)}
          onLaunched={(runId) => {
            setApplyTarget(null);
            addToast({
              type: 'success',
              title: t('clash.profiles.runStarted', {
                defaultValue: 'Run created from profile',
              }),
            });
            navigate(
              `/clash?run=${runId}${ctxProjectId ? '' : `&project=${projectId}`}`,
            );
          }}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

// ── Detail (read-only view) ───────────────────────────────────────────

function ProfileDetail({
  profile,
  onEdit,
  onDuplicate,
  onDelete,
  onApply,
}: {
  profile: ClashProfile;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onApply: () => void;
}) {
  const { t } = useTranslation();
  const rows: Array<[string, string]> = [
    [
      t('clash.profiles.field.type', { defaultValue: 'Clash type' }),
      profile.clash_type,
    ],
    [
      t('clash.profiles.field.mode', { defaultValue: 'Mode' }),
      profile.mode,
    ],
    [
      t('clash.profiles.field.tolerance', { defaultValue: 'Tolerance' }),
      `${Math.round(profile.tolerance_m * 1000)} mm`,
    ],
    [
      t('clash.profiles.field.clearance', { defaultValue: 'Clearance' }),
      `${Math.round(profile.clearance_m * 1000)} mm`,
    ],
    [
      t('clash.profiles.field.grid', { defaultValue: 'Spatial grid' }),
      `${profile.spatial_grid_mm} mm`,
    ],
    [
      t('clash.profiles.field.ignoreSameModel', {
        defaultValue: 'Ignore same-model',
      }),
      profile.ignore_same_model
        ? t('common.yes', { defaultValue: 'Yes' })
        : t('common.no', { defaultValue: 'No' }),
    ],
    [
      t('clash.profiles.field.rules', { defaultValue: 'Rules' }),
      String(profile.rules.length),
    ],
  ];

  return (
    <Card padding="none" className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-content-primary truncate">
            {profile.name}
          </h2>
          {profile.description && (
            <p className="text-sm text-content-secondary mt-1 whitespace-pre-line">
              {profile.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            icon={<Play className="w-4 h-4" />}
            onClick={onApply}
          >
            {t('clash.profiles.apply', { defaultValue: 'Apply' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Pencil className="w-4 h-4" />}
            onClick={onEdit}
          >
            {t('common.edit', { defaultValue: 'Edit' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Copy className="w-4 h-4" />}
            onClick={onDuplicate}
          >
            {t('common.duplicate', { defaultValue: 'Duplicate' })}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="w-4 h-4" />}
            onClick={onDelete}
          >
            {t('common.delete', { defaultValue: 'Delete' })}
          </Button>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 border-b border-border-light pb-1.5">
            <dt className="text-sm text-content-tertiary">{label}</dt>
            <dd className="text-sm font-medium text-content-primary text-right">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 text-xs text-content-tertiary">
        {t('clash.profiles.editHint', {
          defaultValue:
            'Selection sets and per-discipline rules are authored on the Clash detection page and carried with the profile.',
        })}
      </p>
    </Card>
  );
}

// ── Editor (create / edit form) ───────────────────────────────────────

function ProfileEditor({
  form,
  setForm,
  creating,
  saving,
  onSave,
  onCancel,
}: {
  form: ProfileForm;
  setForm: (f: ProfileForm) => void;
  creating: boolean;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const set = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) =>
    setForm({ ...form, [key]: value });

  const inputCls =
    'w-full rounded-lg border border-border-subtle bg-surface-1 px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';
  const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

  return (
    <Card padding="none" className="p-5">
      <h2 className="text-lg font-semibold text-content-primary mb-4">
        {creating
          ? t('clash.profiles.createTitle', { defaultValue: 'New profile' })
          : t('clash.profiles.editTitle', { defaultValue: 'Edit profile' })}
      </h2>

      <div className="space-y-4">
        <div>
          <label className={labelCls} htmlFor="profile-name">
            {t('clash.profiles.field.name', { defaultValue: 'Name' })}
          </label>
          <input
            id="profile-name"
            className={inputCls}
            value={form.name}
            maxLength={255}
            onChange={(e) => set('name', e.target.value)}
            placeholder={t('clash.profiles.namePlaceholder', {
              defaultValue: 'e.g. MEP × Structural',
            })}
          />
        </div>

        <div>
          <label className={labelCls} htmlFor="profile-desc">
            {t('clash.profiles.field.description', {
              defaultValue: 'Description',
            })}
          </label>
          <textarea
            id="profile-desc"
            className={clsx(inputCls, 'min-h-[64px] resize-y')}
            value={form.description}
            maxLength={2000}
            onChange={(e) => set('description', e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className={labelCls} htmlFor="profile-type">
              {t('clash.profiles.field.type', { defaultValue: 'Clash type' })}
            </label>
            <select
              id="profile-type"
              className={inputCls}
              value={form.clash_type}
              onChange={(e) => set('clash_type', e.target.value as ClashType)}
            >
              {CLASH_TYPES.map((ct) => (
                <option key={ct} value={ct}>
                  {ct}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="profile-mode">
              {t('clash.profiles.field.mode', { defaultValue: 'Mode' })}
            </label>
            <select
              id="profile-mode"
              className={inputCls}
              value={form.mode}
              onChange={(e) => set('mode', e.target.value)}
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className={labelCls} htmlFor="profile-tol">
              {t('clash.profiles.field.toleranceMm', {
                defaultValue: 'Tolerance (mm)',
              })}
            </label>
            <input
              id="profile-tol"
              type="number"
              min={0}
              max={10000}
              className={inputCls}
              value={form.toleranceMm}
              onChange={(e) =>
                set('toleranceMm', Math.max(0, Number(e.target.value) || 0))
              }
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="profile-clr">
              {t('clash.profiles.field.clearanceMm', {
                defaultValue: 'Clearance (mm)',
              })}
            </label>
            <input
              id="profile-clr"
              type="number"
              min={0}
              max={50000}
              className={inputCls}
              value={form.clearanceMm}
              onChange={(e) =>
                set('clearanceMm', Math.max(0, Number(e.target.value) || 0))
              }
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="profile-grid">
              {t('clash.profiles.field.gridMm', {
                defaultValue: 'Spatial grid (mm)',
              })}
            </label>
            <input
              id="profile-grid"
              type="number"
              min={100}
              max={5000}
              className={inputCls}
              value={form.spatial_grid_mm}
              onChange={(e) =>
                set(
                  'spatial_grid_mm',
                  Math.min(5000, Math.max(100, Number(e.target.value) || 500)),
                )
              }
            />
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="rounded border-border-strong"
            checked={form.ignore_same_model}
            onChange={(e) => set('ignore_same_model', e.target.checked)}
          />
          {t('clash.profiles.field.ignoreSameModel', {
            defaultValue: 'Ignore same-model clashes (federated runs)',
          })}
        </label>
      </div>

      <div className="flex items-center justify-end gap-2 mt-6">
        <Button
          variant="secondary"
          size="sm"
          icon={<X className="w-4 h-4" />}
          onClick={onCancel}
          disabled={saving}
        >
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          size="sm"
          icon={
            saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )
          }
          onClick={onSave}
          disabled={saving}
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  );
}

// ── Apply modal (launch a run from a profile) ─────────────────────────

function ApplyModal({
  projectId,
  profile,
  onClose,
  onLaunched,
}: {
  projectId: string;
  profile: ClashProfile;
  onClose: () => void;
  onLaunched: (runId: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [selModels, setSelModels] = useState<string[]>([]);
  const [runName, setRunName] = useState('');

  const modelsQuery = useQuery({
    queryKey: ['clash-models', projectId],
    queryFn: () => clashApi.models(projectId),
    enabled: !!projectId,
  });
  const models = modelsQuery.data ?? [];

  const applyMut = useMutation({
    mutationFn: () =>
      clashApi.applyProfile(projectId, profile.id, {
        model_ids: selModels,
        name: runName.trim() || undefined,
        carry_forward: true,
      }),
    onSuccess: (run) => onLaunched(run.id),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const toggleModel = useCallback((id: string) => {
    setSelModels((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id],
    );
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-surface-0 shadow-xl border border-border-subtle"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <h2 className="text-base font-semibold text-content-primary flex items-center gap-2">
            <Play className="w-4 h-4 text-oe-blue" />
            {t('clash.profiles.applyTitle', {
              defaultValue: 'Run "{{name}}"',
              name: profile.name,
            })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="h-7 w-7 flex items-center justify-center rounded text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1" htmlFor="apply-run-name">
              {t('clash.profiles.runName', {
                defaultValue: 'Run name (optional)',
              })}
            </label>
            <input
              id="apply-run-name"
              className="w-full rounded-lg border border-border-subtle bg-surface-1 px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              value={runName}
              maxLength={255}
              onChange={(e) => setRunName(e.target.value)}
              placeholder={profile.name}
            />
          </div>

          <div>
            <p className="text-xs font-medium text-content-secondary mb-2">
              {t('clash.profiles.selectModels', {
                defaultValue: 'Models to test',
              })}
            </p>
            {modelsQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-content-tertiary py-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : models.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('clash.profiles.noModels', {
                  defaultValue:
                    'This project has no BIM models yet - upload one first.',
                })}
              </p>
            ) : (
              <div className="max-h-56 overflow-y-auto space-y-1 rounded-lg border border-border-light p-1.5">
                {models.map((m) => (
                  <label
                    key={m.id}
                    className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg hover:bg-surface-1 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      className="rounded border-border-strong"
                      checked={selModels.includes(m.id)}
                      onChange={() => toggleModel(m.id)}
                    />
                    <span className="flex-1 min-w-0 truncate text-sm text-content-primary">
                      {m.name}
                    </span>
                    <span className="text-xs text-content-tertiary shrink-0">
                      {t('clash.profiles.elementCount', {
                        defaultValue: '{{count}} el.',
                        count: m.element_count,
                      })}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-border-light">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            size="sm"
            icon={
              applyMut.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )
            }
            disabled={selModels.length === 0 || applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            {t('clash.profiles.createRun', { defaultValue: 'Create run' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
