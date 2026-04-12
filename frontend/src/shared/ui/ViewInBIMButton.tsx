/**
 * ViewInBIMButton — small reusable button that navigates to the BIM 3D
 * viewer with a set of elements isolated.  Used across Schedule, Tasks,
 * Requirements, Validation, and any other module that links to BIM geometry.
 *
 * Navigation target: `/bim?isolate=id1,id2,...`
 */

import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Cuboid } from 'lucide-react';

export interface ViewInBIMButtonProps {
  /** Array of BIM element IDs to isolate in the 3D viewer. */
  elementIds: string[];
  /** Optional label override.  Defaults to "{count} element(s)". */
  label?: string;
  /** Optional extra CSS classes on the outer button. */
  className?: string;
  /** Icon size in pixels.  Default 12. */
  iconSize?: number;
}

export function ViewInBIMButton({
  elementIds,
  label,
  className,
  iconSize = 12,
}: ViewInBIMButtonProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const validIds = elementIds?.filter(
    (x): x is string => typeof x === 'string' && x.length > 0,
  );

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!validIds || validIds.length === 0) return;
      navigate(`/bim?isolate=${validIds.join(',')}`);
    },
    [navigate, validIds],
  );

  if (!validIds || validIds.length === 0) return null;

  const displayLabel =
    label ??
    t('common.view_in_bim_count', {
      defaultValue: '{{count}} element(s)',
      count: validIds.length,
    });

  return (
    <button
      type="button"
      onClick={handleClick}
      className={
        className ??
        'inline-flex items-center gap-1 text-xs text-oe-blue hover:text-oe-blue-dark transition-colors'
      }
      title={t('common.view_in_bim', {
        defaultValue: 'View in BIM 3D',
      })}
    >
      <Cuboid size={iconSize} className="shrink-0" />
      {displayLabel}
    </button>
  );
}
