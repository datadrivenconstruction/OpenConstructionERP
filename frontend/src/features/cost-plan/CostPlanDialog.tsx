// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The NRM 1 cost plan, opened over the bill it is built from.
 *
 * It lives beside the bill rather than on a route of its own: the plan is a
 * second reading of the same bill, and the estimator moves between the two,
 * fixing a code in the grid and looking again. The view only mounts while the
 * dialog is open, so the bill editor pays nothing for it until it is asked.
 */

import { useTranslation } from 'react-i18next';
import { WideModal } from '@/shared/ui';
import { CostPlanView } from './CostPlanView';

export interface CostPlanDialogProps {
  boqId: string;
  boqName: string;
  open: boolean;
  onClose: () => void;
}

export function CostPlanDialog({ boqId, boqName, open, onClose }: CostPlanDialogProps) {
  const { t } = useTranslation();
  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="full"
      testId="cost-plan-dialog"
      title={t('cost_plan.title', { defaultValue: 'NRM 1 elemental cost plan' })}
      subtitle={t('cost_plan.subtitle', {
        defaultValue:
          '{{name}} rolled up by its NRM codes into group elements 0-8, with the bill\'s own markups below. Nothing here changes the bill.',
        name: boqName,
      })}
    >
      {open && <CostPlanView boqId={boqId} />}
    </WideModal>
  );
}
