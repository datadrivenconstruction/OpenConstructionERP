// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Collapsible "Referenced in N" panel for the file preview pane.
 *
 * Groups references by ``target_type`` so the headline reads
 * "Referenced in 3 RFIs, 1 task". Each chip is a link to the target
 * entity — navigation is delegated to ``onChipClick`` so the host
 * page can pick its own router.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Skeleton } from '@/shared/ui/Skeleton';
import { useReferencesForFile } from './hooks';
import type { FileKind, FileReferenceResponse, TargetType } from './types';
import { fmtList } from '@/shared/lib/formatters';

export interface ReferencedInPanelProps {
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  onChipClick?: (ref: FileReferenceResponse) => void;
  className?: string;
}

const TARGET_PLURAL: Record<TargetType, string> = {
  rfi: 'RFIs',
  issue: 'issues',
  task: 'tasks',
  submittal: 'submittals',
  punch_item: 'punch items',
  change_order: 'change orders',
  meeting: 'meetings',
  field_report: 'field reports',
  tender_package: 'tender packages',
  bid: 'bids',
  contract: 'contracts',
  transmittal: 'transmittals',
  inspection: 'inspections',
  ncr: 'NCRs',
  bcf_topic: 'BCF topics',
  boq_position: 'BOQ positions',
  project: 'projects',
  clash_run: 'clash runs',
};

function pluralizeSummary(byType: Map<TargetType, FileReferenceResponse[]>): string {
  // "Referenced in 3 RFIs, 1 task" — compact, sorted by count desc.
  const entries = Array.from(byType.entries()).sort(
    (a, b) => b[1].length - a[1].length,
  );
  return fmtList(entries
    .map(
      ([t, refs]) =>
        `${refs.length} ${refs.length === 1 ? TARGET_PLURAL[t].replace(/s$/, '') : TARGET_PLURAL[t]}`,
    ));
}

export function ReferencedInPanel({
  projectId,
  fileKind,
  fileId,
  onChipClick,
  className,
}: ReferencedInPanelProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading } = useReferencesForFile({
    projectId,
    kind: fileKind,
    fileId,
  });

  const refs = data?.items ?? [];
  const byType = useMemo(() => {
    const m = new Map<TargetType, FileReferenceResponse[]>();
    refs.forEach((r) => {
      const list = m.get(r.target_type) ?? [];
      list.push(r);
      m.set(r.target_type, list);
    });
    return m;
  }, [refs]);

  if (isLoading) {
    return (
      <div className={clsx('p-3', className)}>
        <Skeleton height={16} className="w-32" />
      </div>
    );
  }
  if (refs.length === 0) return null;

  const summary = pluralizeSummary(byType);

  return (
    <div
      className={clsx(
        'rounded-lg border border-border bg-surface-primary p-3',
        className,
      )}
      data-testid="referenced-in-panel"
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={expanded}
        data-testid="referenced-in-toggle"
      >
        <span className="text-sm font-medium text-content-primary">
          {t('files.referenced_in_label', {
            defaultValue: 'Referenced in {{summary}}',
            summary,
          })}
        </span>
        <span
          aria-hidden="true"
          className={clsx(
            'text-xs text-content-tertiary transition-transform',
            expanded && 'rotate-180',
          )}
        >
          ▾
        </span>
      </button>
      {expanded && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {refs.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => onChipClick?.(r)}
              className="flex items-center gap-1 rounded-full border border-border bg-surface-secondary px-2 py-0.5 text-xs text-content-primary hover:bg-surface-tertiary"
              data-testid={`referenced-chip-${r.id}`}
            >
              <span className="font-mono uppercase text-content-tertiary">
                {r.target_type.replace(/_/g, ' ')}
              </span>
              <span className="font-medium">
                {r.target_label ?? r.target_id.slice(0, 8)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
