import { useTranslation } from 'react-i18next';

import {
  FACET_ALL,
  FACET_UNSET,
  facetOptions,
  type ProjectFacetFilters,
  type ProjectFacetKey,
} from '@/shared/lib/projectFacets';

type Faceted = { phase?: string | null; project_type?: string | null };

interface ProjectFacetSelectsProps {
  projects: readonly Faceted[];
  value: ProjectFacetFilters;
  onChange: (next: ProjectFacetFilters) => void;
  /** Extra classes for each select, so a toolbar and a dropdown can size them. */
  selectClassName?: string;
}

function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Phase and project-type selects for a list of projects. A select appears only
 * when the projects carry that field, and it always keeps the current choice
 * selectable, so a filter that matches nothing can still be cleared.
 */
export function ProjectFacetSelects({ projects, value, onChange, selectClassName = 'oe-select sm:w-40' }: ProjectFacetSelectsProps) {
  const { t } = useTranslation();

  const label = (key: ProjectFacetKey, option: string): string => {
    if (option === FACET_UNSET) return t('projects.facet_unset', { defaultValue: 'Not set' });
    if (key === 'phase') return t(`projects.phase_${option}`, { defaultValue: humanize(option) });
    return option;
  };

  const render = (key: ProjectFacetKey) => {
    const options = facetOptions(projects, key);
    const current = value[key];
    if (current !== FACET_ALL && !options.includes(current)) options.push(current);
    if (options.length === 0) return null;
    const allLabel =
      key === 'phase'
        ? t('projects.facet_all_phases', { defaultValue: 'All phases' })
        : t('projects.facet_all_types', { defaultValue: 'All project types' });
    const aria =
      key === 'phase'
        ? t('projects.facet_phase_aria', { defaultValue: 'Filter projects by phase' })
        : t('projects.facet_type_aria', { defaultValue: 'Filter projects by project type' });
    return (
      <select
        key={key}
        value={current}
        onChange={(e) => onChange({ ...value, [key]: e.target.value })}
        aria-label={aria}
        className={selectClassName}
      >
        <option value={FACET_ALL}>{allLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {label(key, option)}
          </option>
        ))}
      </select>
    );
  };

  return (
    <>
      {render('phase')}
      {render('project_type')}
    </>
  );
}
