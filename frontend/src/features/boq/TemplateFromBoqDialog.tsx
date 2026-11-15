// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Save as template" / "From an existing estimate".
 *
 * With `boqId` the estimate is fixed (opened from the estimate itself); without
 * it the dialog first asks for a project and one of its estimates. The server
 * copies structure, descriptions, units and classification codes and never the
 * project links, actuals or attachments; the checkboxes decide about numbers.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { projectsApi } from '@/features/projects/api';
import { boqApi } from './api';
import { templatesApi, type TemplateDetail } from './templatesApi';

interface Props {
  /** Fixed source estimate; omit to let the user pick one. */
  boqId?: string;
  boqName?: string;
  onClose: () => void;
  onCreated?: (template: TemplateDetail) => void;
}

export function TemplateFromBoqDialog({ boqId, boqName, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useActiveProjectId();

  const [projectId, setProjectId] = useState(activeProjectId);
  const [pickedBoqId, setPickedBoqId] = useState('');
  const [name, setName] = useState(boqName ?? '');
  const [standard, setStandard] = useState('');
  const [keepQuantities, setKeepQuantities] = useState(false);
  const [keepRates, setKeepRates] = useState(true);
  const [includeMarkups, setIncludeMarkups] = useState(false);
  const [renumber, setRenumber] = useState(true);

  const sourceId = boqId ?? pickedBoqId;

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsApi.list(),
    enabled: !boqId,
    staleTime: 5 * 60_000,
  });
  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: !boqId && !!projectId,
    staleTime: 60_000,
  });

  const create = useMutation({
    mutationFn: () =>
      templatesApi.fromBoq({
        boq_id: sourceId,
        name: name.trim() || undefined,
        classification_standard: standard.trim(),
        keep_quantities: keepQuantities,
        keep_rates: keepRates,
        include_markups: includeMarkups,
        renumber,
      }),
    onSuccess: (tpl) => {
      void queryClient.invalidateQueries({ queryKey: ['boq-templates'] });
      addToast({
        type: 'success',
        title: t('boq_templates.created', { defaultValue: 'Template created' }),
        message: tpl.name,
      });
      onCreated?.(tpl);
      onClose();
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq_templates.create_failed', { defaultValue: 'Could not create the template' }),
        message: e.message,
      });
    },
  });

  const check = (
    id: string,
    checked: boolean,
    set: (v: boolean) => void,
    label: string,
    hint?: string,
  ) => (
    <label className="flex items-start gap-2 text-sm text-content-primary">
      <input
        id={id}
        type="checkbox"
        className="mt-0.5"
        checked={checked}
        onChange={(e) => set(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-content-tertiary">{hint}</span>}
      </span>
    </label>
  );

  const title = boqId
    ? t('boq_templates.save_as_template', { defaultValue: 'Save as template' })
    : t('boq_templates.from_estimate', { defaultValue: 'From an existing estimate' });

  return (
    <div
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <form
        className="w-full max-w-md space-y-3 rounded-xl bg-surface-primary p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (sourceId && !create.isPending) create.mutate();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
      >
        <h2 className="oe-section-title">{title}</h2>
        <p className="text-xs text-content-secondary">
          {t('boq_templates.from_estimate_hint', {
            defaultValue:
              'Copies the structure, descriptions, units and classification codes. Project links, actuals and attachments are not copied. Empty sections are left out.',
          })}
        </p>

        {!boqId && (
          <>
            <label className="block text-sm">
              <span className="oe-overline">{t('boq_templates.project', { defaultValue: 'Project' })}</span>
              <select
                className="oe-input mt-1 w-full"
                value={projectId}
                data-testid="tpl-from-boq-project"
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setPickedBoqId('');
                }}
              >
                <option value="">{t('boq_templates.pick_project', { defaultValue: 'Select a project' })}</option>
                {(projects ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="oe-overline">{t('boq_templates.estimate', { defaultValue: 'Estimate' })}</span>
              <select
                className="oe-input mt-1 w-full"
                value={pickedBoqId}
                data-testid="tpl-from-boq-estimate"
                onChange={(e) => {
                  setPickedBoqId(e.target.value);
                  const b = (boqs ?? []).find((x) => x.id === e.target.value);
                  if (b && !name) setName(b.name);
                }}
              >
                <option value="">{t('boq_templates.pick_estimate', { defaultValue: 'Select an estimate' })}</option>
                {(boqs ?? []).map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        <label className="block text-sm">
          <span className="oe-overline">{t('boq_templates.template_name', { defaultValue: 'Template name' })}</span>
          <input
            className="oe-input mt-1 w-full"
            value={name}
            maxLength={255}
            data-testid="tpl-from-boq-name"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="oe-overline">
            {t('boq_templates.standard', { defaultValue: 'Classification standard' })}
          </span>
          <input
            className="oe-input mt-1 w-full"
            value={standard}
            maxLength={50}
            placeholder={t('boq_templates.standard_hint', { defaultValue: 'for example din276, nrm, masterformat' })}
            onChange={(e) => setStandard(e.target.value)}
          />
        </label>

        <div className="space-y-2">
          {check('tpl-keep-qty', keepQuantities, setKeepQuantities, t('boq_templates.keep_quantities', { defaultValue: 'Keep quantities as defaults' }), t('boq_templates.keep_quantities_hint', { defaultValue: 'Leave off to start every quantity blank.' }))}
          {check('tpl-keep-rate', keepRates, setKeepRates, t('boq_templates.keep_rates', { defaultValue: 'Keep unit rates' }))}
          {check('tpl-markups', includeMarkups, setIncludeMarkups, t('boq_templates.include_markups', { defaultValue: 'Include markups' }))}
          {check('tpl-renumber', renumber, setRenumber, t('boq_templates.renumber', { defaultValue: 'Renumber sections and positions' }))}
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button type="submit" size="sm" disabled={!sourceId} loading={create.isPending}>
            {t('boq_templates.create_template', { defaultValue: 'Create template' })}
          </Button>
        </div>
      </form>
    </div>
  );
}
