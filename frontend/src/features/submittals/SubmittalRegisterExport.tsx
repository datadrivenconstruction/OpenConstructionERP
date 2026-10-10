// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The export control of the submittal register.
 *
 * The other site registers are printed whole and their shared control says
 * so. This route also takes the filters the list takes, and names the
 * document after the type it is cut by, so the control is built on the same
 * menu with a note of its own: it exports what the tabs and filters show, and
 * says which parts of the screen (the search box, the order, the one cut the
 * route has no parameter for) the document does not follow.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { DocumentExportMenu, type DocumentExportItem } from '@/shared/ui/DocumentExportMenu';
import { downloadSubmittalRegister } from './api';
import { hasServerFilter, toExportFilters, type RegisterFilters } from './registerView';

export function SubmittalRegisterExport({
  projectId,
  filters,
  empty,
}: {
  projectId: string;
  filters: RegisterFilters;
  /** True when the project's register is known to hold no record at all. */
  empty: boolean;
}) {
  const { t } = useTranslation();

  const items = useMemo<DocumentExportItem[]>(() => {
    const cut = toExportFilters(filters);
    return [
      {
        id: 'register-pdf',
        label: t('doc_export.as_pdf', { defaultValue: 'PDF document' }),
        kind: 'pdf',
        run: (locale) => downloadSubmittalRegister(projectId, 'pdf', locale, cut),
      },
      {
        id: 'register-xlsx',
        label: t('doc_export.as_xlsx', { defaultValue: 'Excel workbook (.xlsx)' }),
        kind: 'xlsx',
        run: (locale) => downloadSubmittalRegister(projectId, 'xlsx', locale, cut),
      },
    ];
  }, [projectId, filters, t]);

  const disabledReason = !projectId
    ? t('common.select_project_first', { defaultValue: 'Please select a project first' })
    : empty
      ? t('doc_export.empty', { defaultValue: 'There are no records to export yet' })
      : undefined;

  const note = hasServerFilter(filters)
    ? filters.awaiting
      ? t('submittals.export_note_filtered_awaiting', {
          defaultValue:
            'The export follows the type tab and the filters. The search box, the column order and the "Awaiting review" cut are not applied.',
        })
      : t('submittals.export_note_filtered', {
          defaultValue:
            'The export follows the type tab and the filters, and names them in its header. The search box and the column order are not applied.',
        })
    : filters.awaiting
      ? t('submittals.export_note_awaiting', {
          defaultValue:
            'The whole register is exported. The "Awaiting review" cut and the search box are not applied; use the status filter to export one status.',
        })
      : t('submittals.export_note_whole', {
          defaultValue:
            'The whole register is exported. Pick a type tab or a filter to export that cut instead; the search box is not applied.',
        });

  return (
    <DocumentExportMenu
      label={t('submittals.export_register', { defaultValue: 'Export register' })}
      items={items}
      primaryId="register-pdf"
      disabledReason={disabledReason}
      note={note}
      testId="submittals-export"
    />
  );
}
