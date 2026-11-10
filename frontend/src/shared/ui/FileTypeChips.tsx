// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import {
  Box,
  FileText,
  Image as ImageIcon,
  Layers,
  PenTool,
  type LucideIcon,
} from 'lucide-react';

/**
 * FileTypeChips — compact row of "what's uploaded" chips for a project.
 *
 * Raw extensions from ``GET /v1/documents/file-types-by-project/`` are
 * grouped into five high-level buckets so the chips stay scannable even
 * on projects that carry many different formats:
 *
 *   BIM     — rvt / ifc / nwd / nwc / dae        (3D models)
 *   DWG     — dwg / dxf                                (2D drawings)
 *   PDF     — pdf                                      (specs, takeoffs)
 *   Excel   — xlsx / xls / csv                         (schedules, BOQs)
 *   Photo   — jpg / jpeg / png / heic / tiff           (site / takeoff)
 *
 * Only buckets with at least one matching extension render. Tooltip on
 * hover shows the exact extensions. Renders nothing when the project
 * has no documents — keeps the card clean.
 */
export interface FileTypeChipsProps {
  /** Uploaded file extensions for this project (lower-case, no dot). */
  fileTypes?: string[];
  /** Chip scale. ``md`` fits prominent card slots, ``sm`` fits side rows,
   *  ``xs`` fits inline lists. */
  size?: 'xs' | 'sm' | 'md';
  /** Extra CSS on the wrapper row. */
  className?: string;
}

interface Bucket {
  key: string;
  exts: string[];
  label: string;
  icon: LucideIcon;
  color: string;
}

export function FileTypeChips({ fileTypes, size = 'md', className }: FileTypeChipsProps) {
  const { t } = useTranslation();
  if (!fileTypes || fileTypes.length === 0) return null;

  const set = new Set(fileTypes.map((x) => x.toLowerCase()));

  const buckets: Bucket[] = [
    {
      key: 'bim',
      exts: ['rvt', 'ifc', 'nwd', 'nwc', 'dae'],
      label: t('projects.chip_bim', { defaultValue: 'BIM' }),
      icon: Box,
      color:
        'bg-violet-100 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-800',
    },
    {
      key: 'dwg',
      exts: ['dwg', 'dxf'],
      label: t('projects.chip_dwg', { defaultValue: 'DWG' }),
      icon: PenTool,
      color:
        'bg-semantic-warning-bg text-semantic-warning border-semantic-warning/30',
    },
    {
      key: 'pdf',
      exts: ['pdf'],
      label: t('projects.chip_pdf', { defaultValue: 'PDF' }),
      icon: FileText,
      color:
        'bg-semantic-error-bg text-semantic-error border-semantic-error/30',
    },
    {
      key: 'xls',
      exts: ['xlsx', 'xls', 'csv'],
      label: t('projects.chip_excel', { defaultValue: 'Excel' }),
      icon: Layers,
      color:
        'bg-semantic-success-bg text-semantic-success border-semantic-success/30',
    },
    {
      key: 'photo',
      exts: ['jpg', 'jpeg', 'png', 'heic', 'tiff', 'webp'],
      label: t('projects.chip_photo', { defaultValue: 'Photo' }),
      icon: ImageIcon,
      color:
        'bg-semantic-info-bg text-semantic-info border-semantic-info/30',
    },
  ];

  const chips = buckets
    .map((b) => {
      const hits = b.exts.filter((e) => set.has(e));
      return hits.length ? { ...b, hits } : null;
    })
    .filter(Boolean) as Array<Bucket & { hits: string[] }>;

  if (chips.length === 0) return null;

  const sizing =
    size === 'xs'
      ? 'px-1 py-[1px] text-2xs gap-0.5'
      : size === 'sm'
        ? 'px-1.5 py-0.5 text-2xs gap-1'
        : 'px-2 py-0.5 text-2xs gap-1';
  const iconSize = size === 'xs' ? 8 : size === 'sm' ? 10 : 12;
  const gap = size === 'md' ? 'gap-1.5' : 'gap-1';

  return (
    <div className={`flex flex-wrap items-center ${gap} ${className ?? ''}`}>
      {chips.map((c) => {
        const Icon = c.icon;
        return (
          <span
            key={c.key}
            className={`inline-flex items-center rounded-full border font-semibold uppercase tracking-wider ${sizing} ${c.color}`}
            title={c.hits.map((x) => x.toUpperCase()).join(' · ')}
          >
            <Icon size={iconSize} className="shrink-0" />
            {c.label}
          </span>
        );
      })}
    </div>
  );
}
