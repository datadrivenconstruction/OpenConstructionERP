// DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ContractStatusPipeline — compact visual stepper for a single contract.
//
// Renders the four canonical lifecycle stages as a chevron of dots:
//   draft → active → completed
//   (suspended is a side branch off active; terminated is a red collapse)
//
// Mirrors the visual language of POStatusPipeline so the two pipelines
// feel like a single language across the commercial section. The FSM
// itself is enforced backend-side in ContractsService.transition_contract.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import type { ContractStatus } from './api';

const ORDER: ContractStatus[] = ['draft', 'active', 'completed'];

const LABEL_DEFAULT: Record<ContractStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  suspended: 'Suspended',
  completed: 'Completed',
  terminated: 'Terminated',
};

export function ContractStatusPipeline({
  status,
}: {
  status: ContractStatus | string;
}) {
  const { t } = useTranslation();
  // Unknown statuses (typo, deprecated value left over in DB) collapse
  // to 'draft' so the pipeline always renders meaningful state instead
  // of an unlabelled set of grey dots.
  const valid: ContractStatus[] = [
    'draft',
    'active',
    'suspended',
    'completed',
    'terminated',
  ];
  const s: ContractStatus = (valid as string[]).includes(status)
    ? (status as ContractStatus)
    : 'draft';

  const ariaLabel = t('contracts.pipeline_aria', {
    defaultValue: 'Contract status pipeline',
  });
  const currentLabel = t(`contracts.pipeline_${s}`, {
    defaultValue: LABEL_DEFAULT[s],
  });

  // Terminated collapses to a single red bar — same visual convention as
  // POStatusPipeline.cancelled. A terminated contract has no "stages
  // ahead" worth visualising.
  if (s === 'terminated') {
    return (
      <div
        role="img"
        aria-label={`${ariaLabel}: ${currentLabel}`}
        className="inline-flex items-center gap-1"
      >
        <span className="inline-block h-1.5 w-6 rounded-full bg-semantic-error/70" />
      </div>
    );
  }

  // Suspended is shown as an amber pause on the active stage.
  if (s === 'suspended') {
    return (
      <div
        role="img"
        aria-label={`${ariaLabel}: ${currentLabel}`}
        className="inline-flex items-center gap-0.5"
      >
        <span className="inline-block h-1.5 w-2 rounded-full bg-semantic-success/70" />
        <span className="inline-block h-1.5 w-4 rounded-full bg-semantic-warning" />
        <span className="inline-block h-1.5 w-2 rounded-full bg-border" />
      </div>
    );
  }

  const activeIdx = ORDER.indexOf(s);

  return (
    <div
      role="img"
      aria-label={`${ariaLabel}: ${currentLabel}`}
      className="inline-flex items-center gap-0.5"
    >
      {ORDER.map((stage, idx) => {
        const past = idx < activeIdx;
        const current = idx === activeIdx;
        return (
          <span
            key={stage}
            title={t(`contracts.pipeline_${stage}`, {
              defaultValue: LABEL_DEFAULT[stage],
            })}
            className={clsx(
              'inline-block h-1.5 rounded-full transition-colors',
              current ? 'w-4' : 'w-2',
              past && 'bg-semantic-success/70',
              current && 'bg-oe-blue',
              !past && !current && 'bg-border',
            )}
          />
        );
      })}
    </div>
  );
}
