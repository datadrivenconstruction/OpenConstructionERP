// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Sidebar tree item — slots into the file-manager left rail.
 *
 * Renders a row identical in geometry to the existing category rows,
 * with a Trash icon, the localized "Recycle Bin" label, and a count
 * badge driven by ``useFileTrashStats``. Clicking the row navigates
 * to ``/files/trash`` so the user lands on the dedicated trash page.
 */

import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { useFileTrashStats } from './hooks';

interface TrashNodeProps {
  projectId: string | null | undefined;
  /** Highlight as active when the current route is /files/trash. */
  active?: boolean;
  className?: string;
}

export function TrashNode({ projectId, active, className }: TrashNodeProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: stats } = useFileTrashStats(projectId);
  const count = stats?.count ?? 0;

  return (
    <button
      type="button"
      onClick={() => navigate('/files/trash')}
      data-testid="file-tree-trash-node"
      className={clsx(
        'flex w-full items-center gap-2 px-2 py-1.5 rounded-md text-left',
        'text-xs text-content-secondary',
        'hover:bg-surface-secondary hover:text-content-primary',
        'transition-colors',
        active && 'bg-surface-secondary text-content-primary font-medium',
        className,
      )}
      title={t('files.trash.sidebar_title', { defaultValue: 'Recycle Bin' })}
    >
      <Trash2 size={13} strokeWidth={2} className="shrink-0 text-content-tertiary" />
      <span className="flex-1 truncate">
        {t('files.trash.sidebar_label', { defaultValue: 'Recycle Bin' })}
      </span>
      {count > 0 && (
        <span
          className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-semantic-warning/15 text-semantic-warning text-[10px] font-semibold tabular-nums"
          aria-label={t('files.trash.count_aria', {
            defaultValue: '{{count}} items in recycle bin',
            count,
          })}
        >
          {count}
        </span>
      )}
    </button>
  );
}
