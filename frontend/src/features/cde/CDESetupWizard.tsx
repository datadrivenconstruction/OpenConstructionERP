// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CDESetupWizard — guided per-project setup of the common data environment.
//
// Standing up a CDE properly (ISO 19650) is a handful of decisions a team
// should make up front: the naming convention, the suitability-code set, who
// holds each functional role, which review flow gates a publish, and whether a
// go-live gate protects the CDE from being opened to the whole team before it
// has actually been exercised. This wizard walks the project owner through
// those decisions and persists them to the per-project CDE settings. It mirrors
// the multi-step OnboardingWizard shell (stepper + Back/Next/Finish footer).

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileSignature,
  FolderTree,
  Gauge,
  ShieldCheck,
  Tags,
  Users,
} from 'lucide-react';

import { Badge, Button, WideModal, WideModalSection } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  applyCDEApprovalPreset,
  fetchCDEApprovalPresets,
  fetchCDEReadiness,
  fetchCDESettings,
  fetchFunctionalRoles,
  fetchGoLiveGate,
  updateCDESettings,
  type CDEReadinessLevel,
  type CDESettingsUpdate,
} from './api';

const READINESS_LEVELS: CDEReadinessLevel[] = [
  'not_started',
  'forming',
  'operational',
  'mature',
];

/** English fallbacks for `cde.readiness_level_*`, worded as the readiness
 *  scorecard on CDEPage words them so the same level reads the same in the
 *  dropdown and on the badge. Without these the go-live select showed the bare
 *  enum token, `not_started`, to every reader including English ones. */
const READINESS_LEVEL_LABELS: Record<CDEReadinessLevel, string> = {
  not_started: 'Not started',
  forming: 'Forming',
  operational: 'Operational',
  mature: 'Mature',
};

interface ProjectMember {
  user_id: string;
  full_name?: string;
  email: string;
}

export interface CDESetupWizardProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
}

interface WizardDraft {
  naming_convention: string;
  suitability_set: string;
  role_assignments: Record<string, string>;
  review_preset_key: string | null;
  go_live_gate_enabled: boolean;
  min_readiness_level: CDEReadinessLevel;
}

const STEP_COUNT = 5;

export function CDESetupWizard({ open, onClose, projectId }: CDESetupWizardProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<WizardDraft | null>(null);

  const settingsQuery = useQuery({
    queryKey: ['cde-settings', projectId],
    queryFn: () => fetchCDESettings(projectId),
    enabled: open && !!projectId,
  });

  const rolesQuery = useQuery({
    queryKey: ['cde-functional-roles'],
    queryFn: () => fetchFunctionalRoles(),
    enabled: open,
    staleTime: 10 * 60_000,
  });

  const membersQuery = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () =>
      apiGet<ProjectMember[]>(`/v1/projects/${projectId}/members/`),
    enabled: open && !!projectId,
    staleTime: 60_000,
  });

  const presetsQuery = useQuery({
    queryKey: ['cde-approval-presets', projectId],
    queryFn: () => fetchCDEApprovalPresets(projectId),
    enabled: open && !!projectId,
    staleTime: 60_000,
  });

  const readinessQuery = useQuery({
    queryKey: ['cde-readiness', projectId],
    queryFn: () => fetchCDEReadiness(projectId),
    enabled: open && !!projectId,
  });

  const gateQuery = useQuery({
    queryKey: ['cde-go-live', projectId],
    queryFn: () => fetchGoLiveGate(projectId),
    enabled: open && !!projectId,
  });

  // Seed the draft from persisted settings once loaded, and resume on the
  // stored step so a half-finished setup picks up where it was left.
  useEffect(() => {
    if (!open || !settingsQuery.data || draft) return;
    const s = settingsQuery.data;
    setDraft({
      naming_convention: s.naming_convention,
      suitability_set: s.suitability_set || 'iso19650',
      role_assignments: { ...s.role_assignments },
      review_preset_key: s.review_preset_key,
      go_live_gate_enabled: s.go_live_gate_enabled,
      min_readiness_level: s.min_readiness_level,
    });
    setStep(Math.min(s.setup_step ?? 0, STEP_COUNT - 1));
  }, [open, settingsQuery.data, draft]);

  // Reset local state when the modal is closed so the next open re-seeds.
  useEffect(() => {
    if (!open) {
      setDraft(null);
      setStep(0);
    }
  }, [open]);

  const presets = useMemo(() => presetsQuery.data?.presets ?? [], [presetsQuery.data]);
  const members = membersQuery.data ?? [];
  const roles = rolesQuery.data?.roles ?? [];

  const saveMut = useMutation({
    mutationFn: (payload: CDESettingsUpdate) =>
      updateCDESettings(projectId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['cde-settings', projectId] });
      void qc.invalidateQueries({ queryKey: ['cde-go-live', projectId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  // Adopting a preset clones it into a project-scoped, editable route (see
  // POST /v1/cde/approval-presets/apply) - the settings save above only
  // stores the label, this is what actually wires up a working route the
  // team can tailor afterwards in Approval routes.
  const applyPresetMut = useMutation({
    mutationFn: (systemKey: string) => applyCDEApprovalPreset(projectId, systemKey),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['cde-approval-presets', projectId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('cde.preset_apply_failed', { defaultValue: 'Could not adopt preset' }),
        message: e.message,
      }),
  });

  if (!open) return null;

  function patchDraft(patch: Partial<WizardDraft>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
  }

  function memberLabel(m: ProjectMember): string {
    return m.full_name?.trim() || m.email;
  }

  async function persist(extra: CDESettingsUpdate): Promise<void> {
    if (!draft) return;
    await saveMut.mutateAsync({
      naming_convention: draft.naming_convention,
      suitability_set: draft.suitability_set,
      role_assignments: draft.role_assignments,
      review_preset_key: draft.review_preset_key,
      go_live_gate_enabled: draft.go_live_gate_enabled,
      min_readiness_level: draft.min_readiness_level,
      ...extra,
    });
  }

  async function goNext() {
    // Persist progress step by step so the wizard is resumable.
    await persist({ setup_step: Math.min(step + 1, STEP_COUNT - 1) });
    setStep((s) => Math.min(s + 1, STEP_COUNT - 1));
  }

  async function finish() {
    // Adopt the chosen preset into an editable route first (if it isn't
    // already active) so "Finish" leaves the project with a working review
    // flow, not just a label.
    if (
      draft?.review_preset_key &&
      draft.review_preset_key !== presetsQuery.data?.active_system_key
    ) {
      await applyPresetMut.mutateAsync(draft.review_preset_key);
    }
    await persist({ setup_completed: true, setup_step: STEP_COUNT - 1 });
    addToast({
      type: 'success',
      title: t('cde.wizard_saved_title', { defaultValue: 'CDE configured' }),
      message: t('cde.wizard_saved_msg', {
        defaultValue: 'Your common data environment setup has been saved.',
      }),
    });
    onClose();
  }

  const stepMeta = [
    {
      icon: FolderTree,
      title: t('cde.wizard_step_naming', { defaultValue: 'Naming convention' }),
    },
    {
      icon: Tags,
      title: t('cde.wizard_step_suitability', {
        defaultValue: 'Suitability codes',
      }),
    },
    {
      icon: Users,
      title: t('cde.wizard_step_roles', { defaultValue: 'Functional roles' }),
    },
    {
      icon: FileSignature,
      title: t('cde.wizard_step_review', { defaultValue: 'Review flow' }),
    },
    {
      icon: Gauge,
      title: t('cde.wizard_step_golive', { defaultValue: 'Go-live gate' }),
    },
  ];

  const loading =
    settingsQuery.isLoading || !draft || rolesQuery.isLoading;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="lg"
      title={t('cde.wizard_title', { defaultValue: 'Set up the CDE' })}
      subtitle={t('cde.wizard_subtitle', {
        defaultValue:
          'Agree the few things ISO 19650 asks for up front, then open the CDE to the team once it is ready.',
      })}
      busy={saveMut.isPending || applyPresetMut.isPending}
      footer={
        <div className="flex items-center justify-between gap-2 w-full">
          <span className="text-xs text-content-tertiary">
            {t('cde.wizard_step_of', {
              defaultValue: 'Step {{n}} of {{total}}',
              n: step + 1,
              total: STEP_COUNT,
            })}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={step === 0 || saveMut.isPending}
              onClick={() => setStep((s) => Math.max(s - 1, 0))}
              icon={<ArrowLeft size={14} />}
            >
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
            {step < STEP_COUNT - 1 ? (
              <Button
                variant="primary"
                size="sm"
                disabled={loading || saveMut.isPending}
                onClick={() => void goNext()}
                icon={<ArrowRight size={14} />}
              >
                {t('common.next', { defaultValue: 'Next' })}
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                disabled={loading || saveMut.isPending || applyPresetMut.isPending}
                onClick={() => void finish()}
                icon={<Check size={14} />}
              >
                {t('cde.wizard_finish', { defaultValue: 'Finish setup' })}
              </Button>
            )}
          </div>
        </div>
      }
    >
      {/* Stepper rail */}
      <div className="mb-4 flex items-center gap-1 flex-wrap">
        {stepMeta.map((m, i) => {
          const Icon = m.icon;
          const active = i === step;
          const done = i < step;
          return (
            <div
              key={i}
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
                active
                  ? 'bg-oe-blue text-content-inverse'
                  : done
                    ? 'bg-oe-blue-subtle text-oe-blue-text'
                    : 'bg-surface-secondary text-content-tertiary'
              }`}
            >
              {done ? <Check size={12} /> : <Icon size={12} />}
              <span className="hidden sm:inline">{m.title}</span>
            </div>
          );
        })}
      </div>

      {loading ? (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : !draft ? null : (
        <>
          {/* Step 1 — naming convention */}
          {step === 0 && (
            <WideModalSection
              columns={1}
              title={t('cde.wizard_step_naming', {
                defaultValue: 'Naming convention',
              })}
            >
              <p className="text-xs text-content-secondary mb-2 max-w-prose">
                {t('cde.wizard_naming_help', {
                  defaultValue:
                    'Agree how information containers are named so a code tells you the originator, breakdown and number at a glance. Every container in this project follows this pattern.',
                })}
              </p>
              <input
                type="text"
                value={draft.naming_convention}
                onChange={(e) => patchDraft({ naming_convention: e.target.value })}
                placeholder="Project-Originator-Functional-Spatial-Form-Discipline-Number"
                className="w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                aria-label={t('cde.wizard_step_naming', {
                  defaultValue: 'Naming convention',
                })}
              />
            </WideModalSection>
          )}

          {/* Step 2 — suitability set */}
          {step === 1 && (
            <WideModalSection
              columns={1}
              title={t('cde.wizard_step_suitability', {
                defaultValue: 'Suitability codes',
              })}
            >
              <p className="text-xs text-content-secondary mb-2 max-w-prose">
                {t('cde.wizard_suitability_help', {
                  defaultValue:
                    'Suitability codes make a container status and purpose explicit (S0 for WIP, S1-S7 for shared, A1-A5 for published). This project uses the ISO 19650 set.',
                })}
              </p>
              <select
                value={draft.suitability_set}
                onChange={(e) => patchDraft({ suitability_set: e.target.value })}
                className="h-9 rounded-md border border-border bg-surface-primary px-2 text-sm"
                aria-label={t('cde.wizard_step_suitability', {
                  defaultValue: 'Suitability codes',
                })}
              >
                <option value="iso19650">ISO 19650</option>
              </select>
            </WideModalSection>
          )}

          {/* Step 3 — functional roles */}
          {step === 2 && (
            <WideModalSection
              columns={1}
              title={t('cde.wizard_step_roles', {
                defaultValue: 'Functional roles',
              })}
            >
              <p className="text-xs text-content-secondary mb-3 max-w-prose">
                {t('cde.wizard_roles_help', {
                  defaultValue:
                    'Assign the four ISO 19650 functional roles. These are responsibilities in the document workflow, not job titles - the reviewer promotes work into the shared area, the approver authorises a publish.',
                })}
              </p>
              <div className="space-y-2">
                {roles.map((role) => (
                  <div
                    key={role.key}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-primary p-2.5"
                  >
                    <div className="min-w-0">
                      <span className="text-sm font-medium text-content-primary">
                        {role.name}
                      </span>
                      <p className="text-2xs text-content-tertiary truncate max-w-xs">
                        {role.summary}
                      </p>
                    </div>
                    <select
                      value={draft.role_assignments[role.key] ?? ''}
                      onChange={(e) =>
                        patchDraft({
                          role_assignments: {
                            ...draft.role_assignments,
                            ...(e.target.value
                              ? { [role.key]: e.target.value }
                              : {}),
                          },
                        })
                      }
                      className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs shrink-0"
                      aria-label={role.name}
                    >
                      <option value="">
                        {t('cde.wizard_unassigned', {
                          defaultValue: 'Unassigned',
                        })}
                      </option>
                      {members.map((m) => (
                        <option key={m.user_id} value={m.user_id}>
                          {memberLabel(m)}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
                {members.length === 0 && (
                  <p className="text-xs text-content-tertiary">
                    {t('cde.wizard_no_members', {
                      defaultValue:
                        'No project members yet. You can assign roles later once people are on the project.',
                    })}
                  </p>
                )}
              </div>
            </WideModalSection>
          )}

          {/* Step 4 — review flow preset */}
          {step === 3 && (
            <WideModalSection
              columns={1}
              title={t('cde.wizard_step_review', {
                defaultValue: 'Review flow',
              })}
            >
              <p className="text-xs text-content-secondary mb-3 max-w-prose">
                {t('cde.wizard_review_help', {
                  defaultValue:
                    'Pick the review flow that gates a container reaching the published state. These are ready-made ISO 19650 presets; you can build a custom route later in Approval routes.',
                })}
              </p>
              <div className="space-y-2">
                <label className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary p-2.5 cursor-pointer">
                  <input
                    type="radio"
                    name="review-preset"
                    checked={draft.review_preset_key === null}
                    onChange={() => patchDraft({ review_preset_key: null })}
                  />
                  <span className="text-sm text-content-primary">
                    {t('cde.wizard_no_preset', {
                      defaultValue: 'No review flow (decide later)',
                    })}
                  </span>
                </label>
                {presets.map((p) => (
                  <label
                    key={p.system_key}
                    className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary p-2.5 cursor-pointer"
                  >
                    <input
                      type="radio"
                      name="review-preset"
                      checked={draft.review_preset_key === p.system_key}
                      onChange={() =>
                        patchDraft({ review_preset_key: p.system_key })
                      }
                    />
                    <span className="inline-flex items-center gap-2 text-sm text-content-primary">
                      <ShieldCheck size={13} className="text-oe-blue" />
                      {t(`cde.preset_name_${p.system_key}`, { defaultValue: p.name })}
                    </span>
                  </label>
                ))}
              </div>
            </WideModalSection>
          )}

          {/* Step 5 — go-live gate */}
          {step === 4 && (
            <WideModalSection
              columns={1}
              title={t('cde.wizard_step_golive', {
                defaultValue: 'Go-live gate',
              })}
            >
              <p className="text-xs text-content-secondary mb-3 max-w-prose">
                {t('cde.wizard_golive_help', {
                  defaultValue:
                    'The go-live gate stops the whole team being invited onto a CDE that has not actually been exercised. Keep it on until the workflow has been run end to end.',
                })}
              </p>

              {gateQuery.data && (
                <div className="mb-3 rounded-lg border border-border-light bg-surface-primary p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                      {t('cde.wizard_current_readiness', {
                        defaultValue: 'Current readiness',
                      })}
                    </span>
                    <Badge
                      variant={gateQuery.data.allowed ? 'success' : 'warning'}
                      size="sm"
                    >
                      {t(`cde.readiness_level_${readinessQuery.data?.level ?? gateQuery.data.level}`, {
                        defaultValue: gateQuery.data.level,
                      })}{' '}
                      · {gateQuery.data.score}%
                    </Badge>
                  </div>
                  <p className="mt-1.5 text-xs text-content-secondary">
                    {gateQuery.data.allowed
                      ? t('cde.wizard_gate_ready', {
                          defaultValue:
                            'Ready: the CDE meets the required level and the team can be invited.',
                        })
                      : t('cde.wizard_gate_not_ready', {
                          defaultValue:
                            'Not ready yet: exercise the CDE workflow further before inviting the whole team.',
                        })}
                  </p>
                </div>
              )}

              <label className="flex items-center gap-2 mb-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.go_live_gate_enabled}
                  onChange={(e) =>
                    patchDraft({ go_live_gate_enabled: e.target.checked })
                  }
                />
                <span className="text-sm text-content-primary">
                  {t('cde.wizard_gate_enabled', {
                    defaultValue: 'Protect go-live with a readiness gate',
                  })}
                </span>
              </label>

              <div className="flex items-center gap-2">
                <label className="text-xs text-content-secondary">
                  {t('cde.wizard_min_level', {
                    defaultValue: 'Minimum level to go live',
                  })}
                </label>
                <select
                  value={draft.min_readiness_level}
                  disabled={!draft.go_live_gate_enabled}
                  onChange={(e) =>
                    patchDraft({
                      min_readiness_level: e.target.value as CDEReadinessLevel,
                    })
                  }
                  className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs disabled:opacity-50"
                  aria-label={t('cde.wizard_min_level', {
                    defaultValue: 'Minimum level to go live',
                  })}
                >
                  {READINESS_LEVELS.map((lvl) => (
                    <option key={lvl} value={lvl}>
                      {t(`cde.readiness_level_${lvl}`, { defaultValue: READINESS_LEVEL_LABELS[lvl] })}
                    </option>
                  ))}
                </select>
              </div>
            </WideModalSection>
          )}
        </>
      )}
    </WideModal>
  );
}
