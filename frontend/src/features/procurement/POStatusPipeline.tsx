// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// POStatusPipeline - compact visual stepper for a single PO row.
//
// Renders the five-stage life-cycle as a chevron-of-dots:
//   draft → approved → issued → partially_received → completed
//
// The 'approved' stage is the commitment moment (TOP-30 #10); it MUST be
// in the order, otherwise an approved PO collapsed to the 'draft' dot and
// looked un-progressed even though its budget was already committed.
//
// Cancelled POs collapse to a single red dot. The current stage is filled,
// past stages are filled-success, future stages are outlined-muted. The
// component is purely presentational and side-effect free - it reads the
// row status string and maps it to the same FSM the backend service
// enforces (`_PO_STATUS_TRANSITIONS` in procurement/service.py).
//
// COLOUR NOTE - the passed stages take their alpha from `opacity-*` rather
// than from a `bg-semantic-success/70` modifier. They once used the modifier,
// and the `semantic` palette was then declared in tailwind.config.js as plain
// `var(--oe-...)` strings instead of the channel-triplet function form, so
// Tailwind emitted NO rule at all for it. That is not a faint colour, it is
// no background whatsoever: every completed stage rendered fully transparent,
// a draft PO showed five visible pips, approved four and issued three, and
// the further a PO had actually got the less progressed it looked. The
// cancelled bar was invisible for the same reason.
//
// The palette has since been converted to the function form, so the modifier
// would resolve correctly here today. `opacity-*` stays because it keeps this
// control legible without depending on the palette declaration staying right,
// not because the modifier is still broken.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

type PoStatus =
  | 'draft'
  | 'approved'
  | 'issued'
  | 'partially_received'
  | 'completed'
  | 'cancelled';

const ORDER: PoStatus[] = [
  'draft',
  'approved',
  'issued',
  'partially_received',
  'completed',
];

const LABEL_KEY: Record<PoStatus, string> = {
  draft: 'procurement.pipeline_draft',
  approved: 'procurement.pipeline_approved',
  issued: 'procurement.pipeline_issued',
  partially_received: 'procurement.pipeline_partial',
  completed: 'procurement.pipeline_completed',
  cancelled: 'procurement.pipeline_cancelled',
};

const LABEL_DEFAULT: Record<PoStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  issued: 'Issued',
  partially_received: 'Partial',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

export function POStatusPipeline({ status }: { status: string }) {
  const { t } = useTranslation();
  // Unknown statuses (typo, deprecated value left over in DB) collapse
  // to 'draft' so the pipeline always renders meaningful state instead
  // of an unlabelled set of grey dots.
  const raw = (status || 'draft') as PoStatus;
  const s: PoStatus =
    raw === 'cancelled' || ORDER.includes(raw) ? raw : 'draft';
  const isCancelled = s === 'cancelled';
  const activeIdx = isCancelled ? -1 : Math.max(0, ORDER.indexOf(s));

  // Single-line accessible label summarising the full progression. Screen
  // readers get the stage name plus position; sighted users see the dots.
  const ariaLabel = t('procurement.pipeline_aria', {
    defaultValue: 'PO status pipeline',
  });
  const currentLabel = t(LABEL_KEY[s], {
    defaultValue: LABEL_DEFAULT[s],
  });

  if (isCancelled) {
    return (
      <div
        role="img"
        aria-label={`${ariaLabel}: ${currentLabel}`}
        className="inline-flex items-center gap-1"
      >
        <span className="inline-block h-1.5 w-6 rounded-full bg-semantic-error opacity-70" />
      </div>
    );
  }

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
              past && 'bg-semantic-success opacity-70',
              current && 'bg-oe-blue',
              !past && !current && 'bg-border',
            )}
          />
        );
      })}
    </div>
  );
}
