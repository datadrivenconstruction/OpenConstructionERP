// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Link2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** Small marker for an annotation row that is already linked to a BOQ position. */
export function AnnotationLinkedBadge({ linkedBoqPositionId }: { linkedBoqPositionId?: string | null }) {
  const { t } = useTranslation();
  if (!linkedBoqPositionId) return null;
  const label = t('dwg_takeoff.already_linked', { defaultValue: 'Already linked to a BOQ position' });
  return (
    <span
      data-testid="annotation-linked-badge"
      role="img"
      aria-label={label}
      title={label}
      className="flex-shrink-0 text-oe-blue"
    >
      <Link2 size={12} />
    </span>
  );
}
