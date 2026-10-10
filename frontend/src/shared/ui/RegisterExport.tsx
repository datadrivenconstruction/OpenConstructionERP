// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The two export controls every site register carries, built on
 * DocumentExportMenu so they read and behave the same on each screen:
 *
 * - RegisterExportButton: the register of a project as a PDF or a workbook.
 * - RecordPdfButton: the printable form of one record.
 *
 * Both are open to anyone who can read the register (the routes ask for the
 * module's `read` permission), so neither is hidden from a viewer.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Printer } from 'lucide-react';

import type { DocumentFormat } from '@/shared/lib/documentExport';
import { DocumentExportMenu, type DocumentExportItem } from './DocumentExportMenu';

/** One register a screen can export: its heading in the menu and how to fetch it. */
export interface RegisterExportTarget {
  id: string;
  /** Translated name of the register; printed as a heading when a screen has several. */
  title?: string;
  download: (format: DocumentFormat, locale: string) => Promise<void>;
}

export interface RegisterExportButtonProps {
  /** Translated label of the button. */
  label: string;
  /** The project whose register is exported; empty when none is selected. */
  projectId: string;
  /** True when the register is known to hold no record at all, filters aside. */
  empty?: boolean;
  /** The registers on offer; one for most screens. */
  targets: RegisterExportTarget[];
  /** Id of the target the main half downloads as a PDF; the first one by default. */
  primaryTargetId?: string;
  /** Entries listed after the registers, e.g. an export of the current view. */
  extraItems?: DocumentExportItem[];
  locales?: readonly string[];
  /** Translated title of a toast shown once a download has started. */
  successTitle?: string;
  /** Translated title of the failure toast; "Export failed" by default. */
  failedTitle?: string;
  /** `sm` beside small header buttons, `md` beside default ones. */
  size?: 'sm' | 'md';
  testId?: string;
  guide?: string;
  className?: string;
}

export function RegisterExportButton({
  label,
  projectId,
  empty = false,
  targets,
  primaryTargetId,
  extraItems,
  locales,
  successTitle,
  failedTitle,
  size,
  testId,
  guide,
  className,
}: RegisterExportButtonProps) {
  const { t } = useTranslation();

  const items = useMemo<DocumentExportItem[]>(() => {
    const pdf = t('doc_export.as_pdf', { defaultValue: 'PDF document' });
    const xlsx = t('doc_export.as_xlsx', { defaultValue: 'Excel workbook (.xlsx)' });
    const registers = targets.flatMap<DocumentExportItem>((target) => [
      {
        id: `${target.id}-pdf`,
        label: pdf,
        kind: 'pdf',
        group: target.title,
        run: (locale) => target.download('pdf', locale),
      },
      {
        id: `${target.id}-xlsx`,
        label: xlsx,
        kind: 'xlsx',
        group: target.title,
        run: (locale) => target.download('xlsx', locale),
      },
    ]);
    return extraItems ? [...registers, ...extraItems] : registers;
  }, [targets, extraItems, t]);

  const disabledReason = !projectId
    ? t('common.select_project_first', { defaultValue: 'Please select a project first' })
    : empty
      ? t('doc_export.empty', { defaultValue: 'There are no records to export yet' })
      : undefined;

  return (
    <DocumentExportMenu
      label={label}
      items={items}
      primaryId={`${primaryTargetId ?? targets[0]?.id ?? ''}-pdf`}
      locales={locales}
      disabledReason={disabledReason}
      // No register route takes a filter, so the control says so instead of
      // letting a filtered screen suggest a filtered document.
      note={t('doc_export.whole_register', {
        defaultValue: 'The whole register is exported. Filters and search on this screen are not applied.',
      })}
      successTitle={successTitle}
      failedTitle={failedTitle}
      size={size}
      testId={testId}
      guide={guide}
      className={className}
    />
  );
}

export interface RecordPdfButtonProps {
  /** Fetch the form of the record in the given document language. */
  download: (locale: string) => Promise<void>;
  /** Translated label; "Print / PDF" by default. */
  label?: string;
  locales?: readonly string[];
  /** Translated title of a toast shown once the download has started. */
  successTitle?: string;
  testId?: string;
  className?: string;
}

export function RecordPdfButton({ download, label, locales, successTitle, testId, className }: RecordPdfButtonProps) {
  const { t } = useTranslation();
  const items = useMemo<DocumentExportItem[]>(
    () => [
      {
        id: 'pdf',
        label: t('doc_export.as_pdf', { defaultValue: 'PDF document' }),
        kind: 'pdf',
        run: download,
      },
    ],
    [download, t],
  );
  return (
    <DocumentExportMenu
      label={label ?? t('doc_export.print_pdf', { defaultValue: 'Print / PDF' })}
      items={items}
      locales={locales}
      successTitle={successTitle}
      icon={<Printer size={14} />}
      testId={testId}
      className={className}
    />
  );
}
