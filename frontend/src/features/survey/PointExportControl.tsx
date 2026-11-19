// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Export the selected points (or all of them) as CSV, DXF or LandXML. */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { exportPoints, type ExportFormat } from './api';

export function PointExportControl({ projectId, ids = [] }: { projectId: string; ids?: string[] }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [format, setFormat] = useState<ExportFormat>('csv');
  const run = useMutation({
    mutationFn: () => exportPoints(projectId, { ids, format, preset: 'PNEZD' }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  return (
    <div className="flex items-center gap-1">
      <select
        className="oe-input w-28"
        value={format}
        onChange={(e) => setFormat(e.target.value as ExportFormat)}
        aria-label={t('survey.export.format', { defaultValue: 'Export format' })}
      >
        <option value="csv">CSV</option>
        <option value="dxf">DXF</option>
        <option value="landxml">LandXML</option>
      </select>
      <Button variant="secondary" icon={<Download size={16} />} loading={run.isPending} onClick={() => run.mutate()} data-testid="survey-export">
        {ids.length > 0
          ? t('survey.export.selection', { defaultValue: 'Export {{count}} selected', count: ids.length })
          : t('survey.export.all', { defaultValue: 'Export points' })}
      </Button>
    </div>
  );
}
