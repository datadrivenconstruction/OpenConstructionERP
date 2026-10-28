// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The register of a tab as a spreadsheet or a PDF, rendered by the server.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';

import { downloadExport, type ExportWhat } from './api';

/** The two download formats of one export. `label` names the export when a screen offers more than one. */
export function ExportButtons({ projectId, what, label }: { projectId: string; what: ExportWhat; label?: string }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<'pdf' | 'xlsx' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = (format: 'pdf' | 'xlsx') => {
    setBusy(format);
    setError(null);
    downloadExport(projectId, what, format)
      .catch((err: unknown) => setError(getErrorMessage(err)))
      .finally(() => setBusy(null));
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="export-buttons" data-export={what}>
      {label && <span className="text-xs text-content-secondary">{label}</span>}
      <Button variant="ghost" size="sm" icon={<Download size={14} />} loading={busy === 'xlsx'} onClick={() => run('xlsx')}>
        {t('qualityConcept.export.xlsx', { defaultValue: 'Spreadsheet' })}
      </Button>
      <Button variant="ghost" size="sm" icon={<Download size={14} />} loading={busy === 'pdf'} onClick={() => run('pdf')}>
        {t('qualityConcept.export.pdf', { defaultValue: 'PDF' })}
      </Button>
      {error && (
        <span role="alert" className="text-xs text-semantic-error">
          {error}
        </span>
      )}
    </span>
  );
}
