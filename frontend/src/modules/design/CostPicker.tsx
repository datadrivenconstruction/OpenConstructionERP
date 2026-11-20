// Design module (ERP side of the design editor link).
/** Pick or replace the ERP cost item behind a position's unit rate. Reuses the ERP's own cost-match panel. */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { CwicrMatchPanel } from '@/features/costs/CwicrMatchPanel';
import { priceFromCostItem } from './api';
import { tr } from './BriefFields';
import { Suggestions } from './Suggestions';

export function CostPicker({ projectId, positionId, rule, query, unit, regions }: {
  projectId: string; positionId: string; rule: string; query: string; unit: string; regions: string[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const apply = useMutation({
    mutationFn: (costItemId: string) => priceFromCostItem(projectId, positionId, costItemId),
    onSuccess: () => {
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['design-estimate'] });
    },
  });
  return (
    <div className="flex flex-col gap-2" data-testid={`cost-picker-${rule}`}>
      <div>
        <Button variant="secondary" onClick={() => setOpen((v) => !v)} data-testid={`cost-pick-${rule}`}>
          {tr(t, open ? 'design.estimate.cost_pick_close' : 'design.estimate.cost_pick')}
        </Button>
      </div>
      {open && regions.length === 0 && (
        <p className="text-xs text-content-secondary" data-testid={`cost-none-${rule}`}>{tr(t, 'design.estimate.cost_pick_none')}</p>
      )}
      {open && regions.length > 0 && (
        <Suggestions projectId={projectId} positionId={positionId} rule={rule} onDone={() => setOpen(false)} />
      )}
      {open && regions.length > 0 && (
        <CwicrMatchPanel
          initialQuery={query}
          unitHint={unit}
          region={regions[0]}
          onApply={(m) => apply.mutate(m.cost_item_id)}
        />
      )}
      {apply.isError && (
        <p role="alert" className="text-xs text-semantic-error">
          {tr(t, 'design.estimate.cost_pick_failed')} {getErrorMessage(apply.error)}
        </p>
      )}
    </div>
  );
}
