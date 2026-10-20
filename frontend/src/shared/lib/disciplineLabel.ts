import type { TFunction } from 'i18next';

/**
 * Model and element disciplines arrive as plain words from the server
 * ("architecture", "structural", "other"). This maps the common ones to the
 * discipline names the federation screens already translate, so a viewer in
 * another language does not read the raw English word. A value it does not
 * know is returned untouched.
 */
const DISCIPLINE_KEY: Record<string, string> = {
  architecture: 'arch',
  architectural: 'arch',
  arch: 'arch',
  structure: 'struct',
  structural: 'struct',
  struct: 'struct',
  mep: 'mep',
  mechanical: 'mep',
  electrical: 'mep',
  plumbing: 'mep',
  landscape: 'landscape',
  civil: 'civil',
  other: 'other',
};

export function disciplineLabel(t: TFunction, discipline: string | null | undefined): string {
  if (!discipline) return '';
  const key = DISCIPLINE_KEY[discipline.trim().toLowerCase()];
  return key ? t(`bim.federation.disc_${key}`, { defaultValue: discipline }) : discipline;
}
