// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Compact tag chip — color dot + display_name + optional remove (×). */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { X } from 'lucide-react';
import type { TagRecord } from './types';

interface TagPillProps {
  tag: TagRecord;
  removable?: boolean | undefined;
  onRemove?: ((tag: TagRecord) => void) | undefined;
  size?: 'sm' | 'md' | undefined;
  className?: string | undefined;
}

export function TagPill({ tag, removable, onRemove, size = 'sm', className }: TagPillProps) {
  const { t } = useTranslation();
  const dimensions = size === 'md' ? 'h-6 px-2 text-xs' : 'h-5 px-1.5 text-[10px]';

  return (
    <span
      data-testid="tag-pill"
      className={clsx(
        'inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-elevated text-content-secondary font-medium',
        dimensions,
        className,
      )}
      title={tag.display_name}
    >
      <span
        data-testid="tag-pill-dot"
        aria-hidden="true"
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: tag.color }}
      />
      <span className="truncate max-w-[120px]">{tag.display_name}</span>
      {removable && onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(tag);
          }}
          aria-label={t('files.tags.remove', {
            defaultValue: 'Remove tag {{tag}}',
            tag: tag.display_name,
          })}
          className="inline-flex items-center justify-center -me-0.5 ms-0.5 h-3.5 w-3.5 rounded-sm text-content-tertiary hover:text-semantic-error hover:bg-semantic-error/10"
        >
          <X size={9} />
        </button>
      )}
    </span>
  );
}
