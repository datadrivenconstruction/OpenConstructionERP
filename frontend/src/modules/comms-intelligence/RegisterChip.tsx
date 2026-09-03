// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The register reference as a chip: `REG-RFI-25406-0001`, coloured by
 * state, linking into the workspace on that item.
 *
 * Worn by the base modules' rows (RFI, PO, bid package, correspondence)
 * so a record raised through a register says so where the record lives -
 * and one click lands on its workflow, its emails and (for a package)
 * its compare columns.
 */
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { registerItemUrl, type Kind, type RegisterStatus } from './registers-api';

export interface RegisterChipItem {
  item_id: string;
  reference: string;
  kind?: Kind | string | null;
  status?: RegisterStatus;
  is_overdue?: boolean;
  title?: string;
}

const TONE = {
  open:
    'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50',
  overdue:
    'border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300 dark:hover:bg-red-900/50',
  closed:
    'border-border bg-surface-secondary text-content-tertiary hover:bg-surface-tertiary dark:hover:bg-surface-tertiary',
} as const;

export function RegisterChip({
  item,
  className,
}: {
  item: RegisterChipItem;
  className?: string;
}) {
  const { t } = useTranslation();
  // Withdrawn wears the closed tone and says so in the tooltip: it is a
  // record of something that was pulled, not a live reference to chase.
  const wd = item.status === 'withdrawn';
  const tone = wd || item.status === 'closed' ? 'closed' : item.is_overdue ? 'overdue' : 'open';
  const hint =
    wd
      ? t('registers.chip_hint_withdrawn', {
          defaultValue: '{{ref}} was withdrawn - raised in error',
          ref: item.reference,
        })
      : tone === 'overdue'
      ? t('registers.chip_hint_overdue', {
          defaultValue: 'Overdue in the registers - open {{ref}}',
          ref: item.reference,
        })
      : t('registers.chip_hint', {
          defaultValue: 'Raised from the registers - open {{ref}}',
          ref: item.reference,
        });
  return (
    <Link
      to={registerItemUrl(item.item_id, item.kind)}
      // Rows that expand or select on click must not swallow the chip.
      onClick={(e) => e.stopPropagation()}
      title={item.title ? `${hint}\n${item.title}` : hint}
      aria-label={hint}
      className={clsx(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-1.5 py-0.5 font-mono text-2xs font-semibold leading-tight whitespace-nowrap transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60',
        TONE[tone],
        className,
      )}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-70" />
      <span className="truncate">{item.reference}</span>
    </Link>
  );
}
