// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Switch for input tax on assembly components. Off by default: assemblies then
// price exactly as before. On, each component may carry a tax status and rate
// and the assembly reports net cost, tax folded into cost and recoverable tax.
// The default treatment below applies to a component that does not choose its own.

import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi, type Project, type UpdateProjectData } from './api';

export function ProjectComponentTaxCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const enabled = project.component_tax_enabled === true;
  const treatment = project.component_tax_treatment ?? 'recoverable';

  const saveMut = useMutation({
    mutationFn: (patch: UpdateProjectData) => projectsApi.update(project.id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({
        type: 'success',
        title: t('project.settings.saved', { defaultValue: 'Project settings saved' }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('project.settings.save_failed', { defaultValue: 'Failed to save settings' }),
        message: getErrorMessage(err),
      }),
  });

  return (
    <Card padding="lg">
      <CardHeader
        title={t('project.settings.component_tax.title', { defaultValue: 'Input tax on assembly components' })}
        subtitle={t('project.settings.component_tax.subtitle', {
          defaultValue:
            'Split materials and services into net cost and input tax, and decide whether the tax is recoverable or part of the cost. Bill-level tax markups are separate and unchanged.',
        })}
      />
      <div className="mt-4 flex flex-col gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={enabled}
            disabled={saveMut.isPending}
            onChange={(e) => saveMut.mutate({ component_tax_enabled: e.target.checked })}
            className="h-4 w-4 rounded border-border"
          />
          {t('project.settings.component_tax.enable', { defaultValue: 'Calculate input tax on assembly components' })}
        </label>
        {enabled && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor="project-component-tax-treatment" className="text-sm font-medium text-content-primary">
              {t('project.settings.component_tax.treatment', { defaultValue: 'Default treatment of input tax' })}
            </label>
            <select
              id="project-component-tax-treatment"
              value={treatment}
              disabled={saveMut.isPending}
              onChange={(e) =>
                saveMut.mutate({
                  component_tax_treatment: e.target.value as 'recoverable' | 'cost_incorporated',
                })
              }
              className="h-9 w-72 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary"
            >
              <option value="recoverable">
                {t('assemblies.tax.treatment_recoverable', { defaultValue: 'Recoverable (not part of the cost)' })}
              </option>
              <option value="cost_incorporated">
                {t('assemblies.tax.treatment_cost_incorporated', { defaultValue: 'Incorporated into the cost' })}
              </option>
            </select>
            <p className="text-xs text-content-tertiary md:max-w-md">
              {t('project.settings.component_tax.treatment_hint', {
                defaultValue:
                  'Applies to components that do not choose their own. Check the rules of the country and the contract type.',
              })}
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
