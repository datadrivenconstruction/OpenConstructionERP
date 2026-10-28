// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SubmittalStatusPipeline — compact visual stepper for a single submittal
// row.
//
// Renders the four happy-path stages as a chevron-of-dots:
//   draft → submitted → under_review → approved
//
// Off-the-happy-path statuses collapse to a single coloured bar:
//   - rejected            → red
//   - revise_and_resubmit → orange (work bounces back to submitter)
//   - approved_as_noted   → green (treated like 'approved' for the stepper,
//                                  the surrounding badge already differentiates)
//   - closed              → blue (terminal)
//
// The component is purely presentational and side-effect free — it reads
// the row status string and maps it to the same FSM the backend service
// enforces (`_SUBMITTAL_STATUS_TRANSITIONS` in submittals/service.py).

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

type SubmittalStatusName =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'approved_as_noted'
  | 'revise_and_resubmit'
  | 'rejected'
  | 'closed';

// Happy-path ordered progression. Other statuses collapse to a coloured bar.
const ORDER: SubmittalStatusName[] = ['draft', 'submitted', 'under_review', 'approved'];

const LABEL_KEY: Record<SubmittalStatusName, string> = {
  draft: 'submittals.pipeline_draft',
  submitted: 'submittals.pipeline_submitted',
  under_review: 'submittals.pipeline_under_review',
  approved: 'submittals.pipeline_approved',
  approved_as_noted: 'submittals.pipeline_approved_noted',
  revise_and_resubmit: 'submittals.pipeline_revise',
  rejected: 'submittals.pipeline_rejected',
  closed: 'submittals.pipeline_closed',
};

const LABEL_DEFAULT: Record<SubmittalStatusName, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  under_review: 'Under Review',
  approved: 'Approved',
  approved_as_noted: 'Approved as Noted',
  revise_and_resubmit: 'Revise & Resubmit',
  rejected: 'Rejected',
  closed: 'Closed',
};

// Off-path colours for the single-bar variant. Kept opaque so the bar
// reads as a status flag rather than as a faded dot.
const OFF_PATH_BAR_CLS: Partial<Record<SubmittalStatusName, string>> = {
  rejected: 'bg-semantic-error/80',
  revise_and_resubmit: 'bg-orange-500/80',
  approved_as_noted: 'bg-semantic-success/80',
  closed: 'bg-oe-blue/70',
};

export function SubmittalStatusPipeline({ status }: { status: string }) {
  const { t } = useTranslation();
  // Unknown statuses (typo, deprecated value left over in DB) collapse to
  // 'draft' so the pipeline always renders meaningful state instead of an
  // unlabelled set of grey dots.
  const raw = (status || 'draft') as SubmittalStatusName;
  const known: SubmittalStatusName =
    raw in LABEL_DEFAULT ? raw : 'draft';

  const ariaLabel = t('submittals.pipeline_aria', {
    defaultValue: 'Submittal status pipeline',
  });
  const currentLabel = t(LABEL_KEY[known], {
    defaultValue: LABEL_DEFAULT[known],
  });

  // Off-path: single coloured bar. Sighted users get a glanceable flag,
  // screen readers get the explicit status name.
  if (known in OFF_PATH_BAR_CLS) {
    return (
      <div
        role="img"
        aria-label={`${ariaLabel}: ${currentLabel}`}
        className="inline-flex items-center gap-1"
      >
        <span
          className={clsx(
            'inline-block h-1.5 w-6 rounded-full',
            OFF_PATH_BAR_CLS[known],
          )}
        />
      </div>
    );
  }

  const activeIdx = Math.max(0, ORDER.indexOf(known));

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
            title={t(LABEL_KEY[stage], { defaultValue: LABEL_DEFAULT[stage] })}
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
