// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useTranslation } from 'react-i18next';
import { fmtNumber } from '@/shared/lib/formatters';

/** The automatic takeoff in four steps, from the Revit parameter to the BOQ
 *  quantity. Shown above the rules so the page explains its own workflow. */
const TAKEOFF_STEPS = [
  {
    key: 'model',
    text: 'In Revit®, give the elements the parameters you price by (for example Phase Created or a BOQ code), then upload the model.',
  },
  {
    key: 'rule',
    text: 'Create a rule: element category plus property filters. Property names and their values are offered from the model.',
  },
  {
    key: 'position',
    text: 'Point the rule at a BOQ position, or let it create one, and pick the quantity: area, volume, length, weight or count.',
  },
  {
    key: 'apply',
    text: 'Preview to check what matches, then Apply. After a new model version, Apply again and the quantities update.',
  },
] as const;

export function TakeoffFlowSteps() {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t('bim_rules.flow_title', { defaultValue: 'How automatic takeoff works' })}
      className="mb-4 rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3"
      data-testid="bim-rules-flow-steps"
    >
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-content-secondary">
        {t('bim_rules.flow_title', { defaultValue: 'How automatic takeoff works' })}
      </h2>
      <ol className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {TAKEOFF_STEPS.map((step, i) => (
          <li key={step.key} className="flex gap-2 text-[11px] leading-snug text-content-secondary">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-semibold text-oe-blue">
              {fmtNumber(i + 1, 0)}
            </span>
            <span>{t(`bim_rules.flow_step_${step.key}`, { defaultValue: step.text })}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
