// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { CollapsibleSection } from '@/shared/ui';
import { useSurveyAccess } from '@/features/survey/useSurveyAccess';
import { TraverseEntry } from './TraverseEntry';

/** The Traverse tab: the field book first, the compact angle list kept below for quick checks. */
export function TraverseTabHost({ projectId, classic }: { projectId: string | null; classic: ReactNode }) {
  const { t } = useTranslation();
  const { canWrite } = useSurveyAccess();
  return (
    <div className="space-y-5">
      <TraverseEntry projectId={projectId} canWrite={canWrite} />
      <CollapsibleSection storageKey="survey.calc.traverse_classic" title={t('plan.trav.classic', { defaultValue: 'Quick traverse from an angle list' })} defaultCollapsed>
        {classic}
      </CollapsibleSection>
    </div>
  );
}
