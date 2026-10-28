// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CDEApprovalPresetsCard — the ISO 19650 approval-preset library (inc3).
//
// Standing up a CDE review flow from a blank form is a lot to ask of a team
// that just wants Gate A / Gate B to work. This card lists the three
// ready-made, tenant-wide presets (issue for review / comment and return /
// review and publish), shows their steps, and lets the project adopt one in
// a single click. Adopting clones the preset into a project-scoped, editable
// route (see POST /v1/cde/approval-presets/apply) — nothing here is a dead
// end: once adopted, "Edit in Approval routes" hands off to the full editor
// for further tailoring (adding a step, changing SLAs, and so on).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { ShieldCheck, Check, Pencil, Workflow } from 'lucide-react';

import { Badge, Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { applyCDEApprovalPreset, fetchCDEApprovalPresets } from './api';

export function CDEApprovalPresetsCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['cde-approval-presets', projectId],
    queryFn: () => fetchCDEApprovalPresets(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const applyMut = useMutation({
    mutationFn: (systemKey: string) => applyCDEApprovalPreset(projectId, systemKey),
    onMutate: (systemKey: string) => setPendingKey(systemKey),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['cde-approval-presets', projectId] });
      qc.invalidateQueries({ queryKey: ['cde-settings', projectId] });
      addToast({
        type: 'success',
        title: t('cde.preset_applied_title', { defaultValue: 'Review flow adopted' }),
        message: t('cde.preset_applied_msg', {
          defaultValue: '"{{name}}" is now this project\'s editable review route.',
          name: result.route_name,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('cde.preset_apply_failed', { defaultValue: 'Could not adopt preset' }),
        message: e.message,
      }),
    onSettled: () => setPendingKey(null),
  });

  if (!projectId) return null;
  if (isLoading) {
    return (
      <Card padding="md">
        <div className="h-5 w-56 animate-pulse rounded bg-surface-secondary" />
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg bg-surface-secondary" />
          ))}
        </div>
      </Card>
    );
  }
  if (!data || data.presets.length === 0) return null;

  return (
    <Card padding="md">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Workflow size={15} className="text-oe-blue" />
        {t('cde.presets_title', { defaultValue: 'Approval presets' })}
      </h2>
      <p className="mt-1 max-w-2xl text-xs text-content-tertiary">
        {t('cde.presets_intro', {
          defaultValue:
            'Ready-made ISO 19650 review flows for the CDE gates. Adopt one in a click - it clones into a route that is yours to edit, so the tenant-wide original always stays intact for other projects.',
        })}
      </p>

      <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        {data.presets.map((preset) => {
          const active = data.active_system_key === preset.system_key;
          const busy = pendingKey === preset.system_key && applyMut.isPending;
          return (
            <div
              key={preset.system_key}
              className={clsx(
                'flex flex-col rounded-lg border p-3',
                active
                  ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
                  : 'border-border-light bg-surface-secondary/40',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-content-primary">
                  <ShieldCheck size={13} className="text-oe-blue shrink-0" />
                  {t(`cde.preset_name_${preset.system_key}`, { defaultValue: preset.name })}
                </span>
                <Badge variant="blue" size="sm" className="shrink-0">
                  {t('cde.roles_gate', { defaultValue: 'Gate {{gate}}', gate: preset.gate })}
                </Badge>
              </div>
              <p className="mt-1.5 flex-1 text-2xs leading-relaxed text-content-tertiary">
                {t(`cde.preset_desc_${preset.system_key}`, { defaultValue: preset.description })}
              </p>
              <ul className="mt-2 space-y-0.5">
                {preset.steps.map((step) => {
                  const role = step.approver_role
                    ? t(`cde.preset_role_${step.approver_role}`, {
                        defaultValue: step.approver_role,
                      })
                    : t('cde.preset_role_named', { defaultValue: 'named approver' });
                  return (
                    <li key={step.ordinal} className="text-2xs text-content-tertiary">
                      {t('cde.preset_step_summary', {
                        defaultValue: 'Step {{n}}: {{role}}',
                        n: step.ordinal,
                        role,
                      })}
                    </li>
                  );
                })}
              </ul>

              <div className="mt-3">
                {active ? (
                  <div className="flex items-center gap-2">
                    <Badge variant="success" size="sm">
                      <Check size={11} className="mr-1 shrink-0" />
                      {t('cde.preset_active', { defaultValue: 'Active' })}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate('/approval-routes')}
                    >
                      <Pencil size={12} className="mr-1" />
                      {t('cde.preset_edit', { defaultValue: 'Edit in Approval routes' })}
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={applyMut.isPending}
                    onClick={() => applyMut.mutate(preset.system_key)}
                  >
                    {busy
                      ? t('cde.preset_applying', { defaultValue: 'Adopting...' })
                      : t('cde.preset_apply', { defaultValue: 'Adopt' })}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
