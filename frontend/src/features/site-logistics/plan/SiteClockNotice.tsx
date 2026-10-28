// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Says, wherever deliveries are booked, that the site has no time zone yet.
// Without one the server does not check opening hours, quiet hours or permit
// windows, and refuses a booking at an entrance that has opening hours.

import { AlertTriangle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import { useConcept, useWords } from './hooks';
import { tx } from './texts';

export function SiteClockNotice({ projectId, onOpen }: { projectId: string; onOpen: () => void }) {
  const { t } = useWords();
  const concept = useConcept(projectId);
  // Unknown is not missing: nothing is shown while loading or when the read failed.
  if (!concept.data || concept.data.site_timezone) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning/5 p-3 text-sm text-content-primary"
      data-testid="site-clock-notice"
    >
      <AlertTriangle size={15} className="shrink-0 text-semantic-warning" aria-hidden />
      <span className="flex-1">{tx(t, 'concept.timezone_missing')}</span>
      <Button size="sm" variant="secondary" onClick={onOpen}>
        {tx(t, 'concept.set_timezone')}
      </Button>
    </div>
  );
}
