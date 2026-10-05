// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The way into the spreadsheet import from an open schedule, with the dialog
 * it opens.
 *
 * Two looks: a card on the Interchange tab, and a quick-start tile in the empty
 * schedule's "Build your project timeline" state. An empty draft is the most
 * natural place to read a spreadsheet into, so the tile opens the dialog with
 * "replace the contents of this schedule" already chosen.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FileSpreadsheet, Upload } from 'lucide-react';

import { Button, Card } from '@/shared/ui';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { ScheduleSpreadsheetImportDialog } from './ScheduleSpreadsheetImportDialog';

export interface SpreadsheetImportEntryProps {
  projectId: string;
  schedule: { id: string; name: string; status: string };
  variant: 'card' | 'tile';
}

export function SpreadsheetImportEntry({ projectId, schedule, variant }: SpreadsheetImportEntryProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  // Importing writes a schedule: editor work, like creating one.
  const canImport = useHasPermission('schedule.create');

  const dialog = (
    <ScheduleSpreadsheetImportDialog
      open={open}
      onClose={() => setOpen(false)}
      projectId={projectId}
      schedule={schedule}
      defaultTarget={variant === 'tile' ? 'replace' : 'new'}
      onImported={(result) => {
        queryClient.invalidateQueries({ queryKey: ['schedules', projectId] });
        if (result.replaced) queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(schedule.id) });
      }}
    />
  );

  if (variant === 'tile') {
    return (
      <>
        <button
          type="button"
          onClick={() => setOpen(true)}
          disabled={!canImport}
          title={canImport ? undefined : t('errors.forbidden', { defaultValue: "You don't have permission to perform this action." })}
          className="group flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border-light bg-surface-secondary/30 p-6 transition-all hover:border-oe-blue/50 hover:bg-oe-blue-subtle/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 transition-transform group-hover:scale-110 dark:bg-emerald-950/30 dark:text-emerald-400">
            <FileSpreadsheet size={24} />
          </div>
          <div>
            <p className="text-sm font-semibold text-content-primary">
              {t('schedule.tabular_import.quickstart_title', { defaultValue: 'Import from Excel or CSV' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('schedule.tabular_import.quickstart_desc', {
                defaultValue: 'Read activities, dates and links from a spreadsheet',
              })}
            </p>
          </div>
        </button>
        {dialog}
      </>
    );
  }

  return (
    <>
      <Card padding="md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              <FileSpreadsheet size={16} className="text-content-secondary" />
              {t('schedule.tabular_import.card_title', { defaultValue: 'Import from Excel or CSV' })}
            </h3>
            <p className="mt-1 text-xs text-content-secondary">
              {t('schedule.tabular_import.card_desc', {
                defaultValue: 'Read a schedule kept in a spreadsheet into a new schedule, or into this one while it is a draft.',
              })}
            </p>
          </div>
          <Button variant="secondary" icon={<Upload size={16} />} onClick={() => setOpen(true)} disabled={!canImport}>
            {t('schedule.tabular_import.open', { defaultValue: 'Import spreadsheet' })}
          </Button>
        </div>
      </Card>
      {dialog}
    </>
  );
}
