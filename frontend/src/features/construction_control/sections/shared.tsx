// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small shared building blocks for the construction-control pillar sections:
// consistent input styling, status-badge helpers, an element-link chip, and a
// section toolbar. Kept tiny and presentational so each pillar section stays
// focused on its own workflow.

import type { ReactNode } from 'react';
import { Link2 } from 'lucide-react';
import { Badge } from '@/shared/ui';
import type { ElementRef } from '../api';

/** Standard text-input / select styling, matching the NCR + Closeout pages. */
export const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-y';

export const labelCls = 'block text-sm font-medium text-content-primary mb-1.5';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** Render a status string as a coloured badge using a per-status variant map. */
export function StatusBadge({
  status,
  variants,
  label,
}: {
  status: string;
  variants: Record<string, BadgeVariant>;
  label?: string;
}) {
  return (
    <Badge variant={variants[status] ?? 'neutral'} size="sm">
      {label ?? status.replace(/_/g, ' ')}
    </Badge>
  );
}

/** A compact chip describing a resolved model element link (the UER). */
export function ElementLinkChip({ element }: { element: ElementRef }) {
  const label =
    element.element_name ||
    element.stable_id ||
    element.ifc_global_id ||
    element.native_id ||
    element.bim_element_id ||
    'Linked element';
  const detail = [element.source_format, element.element_type].filter(Boolean).join(' / ');
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs text-content-secondary"
      title={detail || undefined}
    >
      <Link2 className="h-3 w-3 shrink-0 text-oe-blue" />
      <span className="max-w-[14rem] truncate">{label}</span>
    </span>
  );
}

/** Render the element links for a record, or nothing when there are none. */
export function ElementLinks({ elements }: { elements: ElementRef[] }) {
  if (!elements || elements.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {elements.map((e) => (
        <ElementLinkChip key={e.id} element={e} />
      ))}
    </div>
  );
}

/** A section header row with a title, optional count, and right-aligned actions. */
export function SectionToolbar({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="flex items-center gap-2 text-base font-semibold text-content-primary">
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-xs font-normal text-content-tertiary">
            {count}
          </span>
        )}
      </h2>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}
