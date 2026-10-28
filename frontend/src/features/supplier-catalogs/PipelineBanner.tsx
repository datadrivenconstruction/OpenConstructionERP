// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import clsx from 'clsx';

/**
 * Contextual "where am I in the commercial pipeline" banner.
 *
 * Every Commercial-section page renders one of these so the user always
 * understands (a) what this page is for, (b) the single most useful next
 * action, and (c) how this stage connects to the neighbouring stages of
 * the commercial pipeline (CRM lead → bid/tender → contract → variations;
 * subcontractors ↔ procurement; supplier-catalogs ↔ costs).
 *
 * Brand-new file local to the feature dir (shared/ui is frozen for this
 * pass) — kept tiny and dependency-free so it can be copied verbatim into
 * every sibling feature dir without drift.
 */

export interface PipelineStep {
  /** Route to navigate to. Omit for the current (active) step. */
  to?: string;
  label: string;
  /** Marks the step the user is currently on. */
  current?: boolean;
}

export function PipelineBanner({
  intro,
  steps,
  className,
}: {
  /** One short sentence: what this page does + the next action. */
  intro: string;
  /** Ordered pipeline stages; the active one has `current: true`. */
  steps: PipelineStep[];
  className?: string;
}) {
  return (
    <div
      className={clsx(
        'rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-3',
        className,
      )}
    >
      <p className="text-sm text-content-secondary leading-relaxed">{intro}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        {steps.map((s, i) => {
          const chip = (
            <span
              className={clsx(
                'inline-flex items-center rounded-md px-2 py-0.5 font-medium ring-1 ring-inset transition-colors',
                s.current
                  ? 'bg-oe-blue text-white ring-oe-blue'
                  : s.to
                    ? 'bg-surface-primary text-content-secondary ring-border-light hover:text-oe-blue hover:ring-oe-blue'
                    : 'bg-surface-primary text-content-tertiary ring-border-light',
              )}
            >
              {s.label}
            </span>
          );
          return (
            <div key={s.label} className="flex items-center gap-1.5">
              {s.to && !s.current ? (
                <Link to={s.to} className="focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded-md">
                  {chip}
                </Link>
              ) : (
                chip
              )}
              {i < steps.length - 1 && (
                <ArrowRight size={12} className="text-content-tertiary shrink-0" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
