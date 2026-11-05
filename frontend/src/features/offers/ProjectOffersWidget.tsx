/** Project overview card: the project's offers, newest first, each opening its offer page. */
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card } from '@/shared/ui/Card';
import { useProjectOffers } from './api';

export function ProjectOffersWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useProjectOffers(projectId);
  const rows = q.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Card padding="md" className="h-full" data-testid="project-offers-widget">
      <h3 className="mb-2 text-sm font-semibold">{t('offers.widget.title', { defaultValue: 'Offers' })}</h3>
      <ul className="space-y-1 text-sm">
        {rows.slice(0, 5).map((o) => (
          <li key={o.id} className="flex items-center justify-between gap-2">
            <Link className="underline" to={`/boq/${o.boq_id}/offer`}>
              {o.number} {o.revision}
            </Link>
            <span className="truncate text-content-tertiary">{o.customer_name}</span>
            <span className="tabular-nums">
              {o.gross} {o.currency}
            </span>
            <span className="text-xs">{t(`offers.status.${o.status}`, { defaultValue: o.status })}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
