// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Download of one delivery model document (decision record, risk matrix or
// package plan) as PDF or as a spreadsheet.

import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { FileSpreadsheet, FileText } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { downloadExport, type ExportFormat, type ExportWhat } from './api';

export function ExportButtons({ projectId, what }: { projectId: string; what: ExportWhat }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const download = useMutation({
    mutationFn: (format: ExportFormat) => downloadExport(projectId, what, format),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <span className="inline-flex items-center gap-1" data-testid={`export-${what}`}>
      <Button
        size="sm"
        variant="ghost"
        icon={<FileText size={14} />}
        loading={download.isPending && download.variables === 'pdf'}
        onClick={() => download.mutate('pdf')}
      >
        {t('delivery_model.ui.export.pdf', { defaultValue: 'PDF' })}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        icon={<FileSpreadsheet size={14} />}
        loading={download.isPending && download.variables === 'xlsx'}
        onClick={() => download.mutate('xlsx')}
      >
        {t('delivery_model.ui.export.xlsx', { defaultValue: 'Spreadsheet' })}
      </Button>
    </span>
  );
}
