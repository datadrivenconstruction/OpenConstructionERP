// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's stated jurisdiction and measurement system.
 *
 * Both start unset and the product never fills them from the country: unset
 * means every consumer keeps deriving the answer from `country_code`, which is
 * what it did before the fields existed. The picker offers exactly the codes
 * the backend accepts (GET /v1/projects/jurisdictions/), narrowed to the
 * project's country when it has one, so it cannot offer a code the save would
 * refuse.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { Button, Card, CardHeader, Skeleton } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  projectsApi,
  type JurisdictionOption,
  type Project,
  type ProjectUnitSystem,
} from './api';
import { regionOptionLabel } from './regionLabel';

const SELECT_CLS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent';

/** The option's reader-language label: a country by its own name, a state by the name it carries. */
export function jurisdictionLabel(option: JurisdictionOption, lang: string): string {
  if (option.kind === 'subdivision') {
    return `${option.name ?? option.code} (${option.code})`;
  }
  const country = regionOptionLabel({ value: option.code, label: option.code, iso: option.code }, lang);
  return country === option.code ? option.code : `${country} (${option.code})`;
}

export function ProjectJurisdictionCard({ project }: { project: Project }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const optionsQ = useQuery<JurisdictionOption[]>({
    queryKey: ['project-jurisdictions'],
    queryFn: projectsApi.jurisdictions,
    staleTime: 60 * 60 * 1000,
  });

  const [jurisdiction, setJurisdiction] = useState<string>(project.jurisdiction ?? '');
  const [unitSystem, setUnitSystem] = useState<string>(project.unit_system ?? '');

  useEffect(() => {
    setJurisdiction(project.jurisdiction ?? '');
    setUnitSystem(project.unit_system ?? '');
  }, [project.jurisdiction, project.unit_system]);

  const country = (project.country_code ?? '').toUpperCase();
  const { countries, subdivisions } = useMemo(() => {
    const all = optionsQ.data ?? [];
    // A project with a country may only name that country or a state in it;
    // the backend refuses any other pair.
    const inScope = country ? all.filter((o) => o.country_code === country) : all;
    const lang = i18n.language;
    const byLabel = (a: JurisdictionOption, b: JurisdictionOption) =>
      jurisdictionLabel(a, lang).localeCompare(jurisdictionLabel(b, lang), lang);
    return {
      countries: inScope.filter((o) => o.kind === 'country').sort(byLabel),
      subdivisions: inScope.filter((o) => o.kind === 'subdivision').sort(byLabel),
    };
  }, [optionsQ.data, country, i18n.language]);

  const saveMut = useMutation({
    mutationFn: () =>
      projectsApi.update(project.id, {
        jurisdiction: jurisdiction || null,
        unit_system: (unitSystem || null) as ProjectUnitSystem | null,
      }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      setJurisdiction(updated.jurisdiction ?? '');
      setUnitSystem(updated.unit_system ?? '');
      addToast({
        type: 'success',
        title: t('project.settings.jurisdiction.saved', {
          defaultValue: 'Jurisdiction and measurement system saved',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const dirty =
    jurisdiction !== (project.jurisdiction ?? '') || unitSystem !== (project.unit_system ?? '');
  // A stored value outside the current list (a country changed since) stays
  // selectable, so opening the page never silently drops it.
  const storedOutsideList =
    !!project.jurisdiction &&
    ![...countries, ...subdivisions].some((o) => o.code === project.jurisdiction);

  return (
    <Card padding="lg" id="jurisdiction">
      <CardHeader
        title={t('project.settings.jurisdiction.title', {
          defaultValue: 'Jurisdiction and measurement system',
        })}
        subtitle={t('project.settings.jurisdiction.subtitle', {
          defaultValue:
            'Only needed when the country alone does not say it: the state or province whose rules apply, or a measurement system other than the country\'s. Left unset, both follow the project\'s country.',
        })}
      />
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <label
            htmlFor="project-jurisdiction-select"
            className="block text-sm font-medium text-content-primary"
          >
            {t('project.settings.jurisdiction.field', { defaultValue: 'Jurisdiction' })}
          </label>
          {optionsQ.isLoading ? (
            <Skeleton className="mt-1.5 h-9 w-full" />
          ) : (
            <select
              id="project-jurisdiction-select"
              value={jurisdiction}
              onChange={(e) => setJurisdiction(e.target.value)}
              className={`mt-1.5 ${SELECT_CLS}`}
            >
              <option value="">
                {t('project.settings.jurisdiction.unset', {
                  defaultValue: 'Not set (follows the country)',
                })}
              </option>
              {storedOutsideList && project.jurisdiction && (
                <option value={project.jurisdiction}>{project.jurisdiction}</option>
              )}
              {countries.length > 0 && (
                <optgroup
                  label={t('project.settings.jurisdiction.group_countries', {
                    defaultValue: 'Countries',
                  })}
                >
                  {countries.map((o) => (
                    <option key={o.code} value={o.code}>
                      {jurisdictionLabel(o, i18n.language)}
                    </option>
                  ))}
                </optgroup>
              )}
              {subdivisions.length > 0 && (
                <optgroup
                  label={t('project.settings.jurisdiction.group_subdivisions', {
                    defaultValue: 'States and provinces',
                  })}
                >
                  {subdivisions.map((o) => (
                    <option key={o.code} value={o.code}>
                      {jurisdictionLabel(o, i18n.language)}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          )}
          <p className="mt-1 text-xs text-content-tertiary">
            {t('project.settings.jurisdiction.field_hint', {
              defaultValue:
                'A state or province lets contracts name the law that applies there. It has to lie in the project\'s country.',
            })}
          </p>
        </div>
        <div>
          <label
            htmlFor="project-unit-system-select"
            className="block text-sm font-medium text-content-primary"
          >
            {t('project.settings.unit_system.field', { defaultValue: 'Measurement system' })}
          </label>
          <select
            id="project-unit-system-select"
            value={unitSystem}
            onChange={(e) => setUnitSystem(e.target.value)}
            className={`mt-1.5 ${SELECT_CLS}`}
          >
            <option value="">
              {t('project.settings.unit_system.unset', {
                defaultValue: 'Not set (follows the country)',
              })}
            </option>
            <option value="metric">
              {t('project.settings.unit_system.metric', { defaultValue: 'Metric (m, m², kg)' })}
            </option>
            <option value="imperial">
              {t('project.settings.unit_system.imperial', { defaultValue: 'Imperial (ft, sq ft, lb)' })}
            </option>
          </select>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('project.settings.unit_system.field_hint', {
              defaultValue:
                'When set, the BOQ unit check measures the bill against this system instead of the one the country\'s regional pack declares.',
            })}
          </p>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end">
        <Button
          variant="primary"
          size="sm"
          icon={<Save size={14} />}
          disabled={!dirty}
          loading={saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  );
}
