// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A refused change to a register that already holds entries, in plain words:
 * what happened, why, and what the person can do.
 *
 * Two refusals list what would have changed. `upgrade_not_additive` comes from
 * adding to an installed module, and should not be reached, since the screens
 * lock everything an upgrade may not change. `layout_conflict` comes from
 * building a register under a name whose entries were kept from an earlier
 * build. The other codes say only what happened. Every code still reads as a
 * sentence, never as the code.
 */
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { fmtList } from '@/shared/lib/formatters';

import { LINK_TARGETS, type LinkTarget, type ModuleSpec, type UpgradeProblem, type UpgradeRefusal } from '../api';
import { TARGET_NAMES, say } from '../copy';

/**
 * The English for each part of a refused change, by the server's code.
 * Translated as `module_builder.upgrade_problem.<code>`.
 */
export const UPGRADE_PROBLEM_TEXT: Record<string, string> = {
  field_removed: '{{field}} would be removed.',
  field_retyped: 'The kind of value {{field}} holds would change.',
  field_new_required: '{{field}} is new and must be filled in, but the entries already kept have nothing in it. Make it optional.',
  field_now_required: '{{field}} cannot become required while {{empty}} entries leave it empty.',
  field_now_optional: '{{field}} cannot stop being required on this server.',
  entity_renamed: 'The internal name of the entries would change.',
  scope_changed: 'Whether the entries belong to a project would change.',
  feature_removed: 'A function already switched on would be switched off.',
  state_removed: 'A stage entries may be at would be removed.',
  rule_removed: 'A check already in use would be removed.',
  rule_changed: 'A check already in use would check something else.',
  options_removed: 'A choice entries may hold would be removed from {{field}}.',
};
const PROBLEM_FALLBACK = 'Something already in use would change.';

/**
 * What happened, for the refusals that carry no list.
 * Translated as `module_builder.upgrade_error.<code>`.
 */
export const UPGRADE_ERROR_TEXT: Record<string, string> = {
  module_quarantined: 'This register is switched off for safety. Build it again from the builder to repair it.',
  links_switched_off: 'It would link to a part of the platform that is switched off here: {{targets}}.',
  upgrade_failed: 'The new version did not start, so the previous one is still serving and nothing recorded was lost.',
  not_installed: 'This register is no longer installed.',
  module_unreadable: 'The saved description of this register could not be read, so there is nothing to add to. Build it again from the builder under the same internal name to repair it. Its entries are kept.',
};
const ERROR_FALLBACK = 'Nothing was changed.';

const LISTED = new Set(['upgrade_not_additive', 'layout_conflict']);

export function RefusalNotice({ refusal, spec }: { refusal: UpgradeRefusal; spec: ModuleSpec }) {
  const { t } = useTranslation();
  const listed = LISTED.has(refusal.code);
  const layout = refusal.code === 'layout_conflict';

  const problemText = (problem: UpgradeProblem) => {
    const field = spec.entity.fields.find((f) => f.name === problem.field);
    return t(`module_builder.upgrade_problem.${problem.code}`, {
      field: problem.label || field?.label || problem.field || '',
      empty: problem.empty ?? 0,
      defaultValue: UPGRADE_PROBLEM_TEXT[problem.code] ?? PROBLEM_FALLBACK,
    });
  };

  const targets = Array.isArray(refusal.params.targets)
    ? fmtList(
        refusal.params.targets
          .filter((x): x is LinkTarget => typeof x === 'string' && (LINK_TARGETS as readonly string[]).includes(x))
          .map((target) => say(t, TARGET_NAMES[target])),
        'prose',
      )
    : '';

  return (
    <div
      role="alert"
      className="space-y-2 rounded-xl border border-semantic-error/30 bg-semantic-error-bg px-4 py-3 text-sm"
      data-testid="module-builder-upgrade-refused"
      data-code={refusal.code}
    >
      <p className="flex items-start gap-2 font-semibold text-semantic-error">
        <AlertTriangle size={15} className="mt-0.5 shrink-0" />
        {layout
          ? t('module_builder.layout_conflict_title', {
              defaultValue: 'Entries are already kept under this name',
            })
          : listed
            ? t('module_builder.upgrade_refused_title', { defaultValue: 'This register cannot be updated this way' })
            : t('module_builder.upgrade_failed_title', { defaultValue: 'The register could not be updated' })}
      </p>

      {listed ? (
        <>
          <p className="text-content-secondary">
            {refusal.records === null
              ? t('module_builder.upgrade_refused_why', {
                  defaultValue: 'It would change what entries already hold, so nothing was changed.',
                })
              : t('module_builder.upgrade_refused_why_count', {
                  count: refusal.records,
                  defaultValue_one: 'It would change what {{count}} entry already holds, so nothing was changed.',
                  defaultValue_other: 'It would change what {{count}} entries already hold, so nothing was changed.',
                })}
          </p>
          {refusal.problems.length > 0 && (
            <ul className="list-disc space-y-0.5 ps-5 text-content-secondary" data-testid="module-builder-upgrade-problems">
              {refusal.problems.map((problem, i) => (
                <li key={`${problem.code}-${i}`}>{problemText(problem)}</li>
              ))}
            </ul>
          )}
          <p className="text-content-secondary">
            {layout
              ? t('module_builder.layout_conflict_action', {
                  defaultValue:
                    'Keep those fields as they were, or choose another internal name under Advanced to start a new register.',
                })
              : t('module_builder.upgrade_refused_action', {
                  defaultValue:
                    'Go back and keep what is already there as it was, adding only new fields, checks and functions. For a different layout, build a new register.',
                })}
          </p>
        </>
      ) : (
        <p className="text-content-secondary">
          {t(`module_builder.upgrade_error.${refusal.code}`, {
            targets,
            defaultValue: UPGRADE_ERROR_TEXT[refusal.code] ?? ERROR_FALLBACK,
          })}
        </p>
      )}
    </div>
  );
}
