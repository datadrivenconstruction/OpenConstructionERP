// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Next to a list's filters: keep the filters on screen as the ones the list
 * opens with, or go back to opening unfiltered. Personal, kept on this device.
 */
import { useTranslation } from 'react-i18next';
import { Button } from './Button';
import {
  defaultFilterPref,
  sameFilter,
  type DefaultFilterPage,
  type FilterValues,
} from '@/shared/lib/defaultFilters';

interface Props {
  page: DefaultFilterPage;
  /** The filters on screen, only the fields worth keeping. */
  current: FilterValues;
  /** The same fields with nothing narrowed. */
  neutral: FilterValues;
}

export function SaveDefaultFilter({ page, current, neutral }: Props) {
  const { t } = useTranslation();
  const saved = defaultFilterPref.use()[page];
  const narrowed = !sameFilter(current, neutral);
  const canSave = narrowed && !(saved && sameFilter(current, saved));

  if (!canSave && !saved) return null;
  return (
    <span className="inline-flex items-center gap-1" data-testid={`default-filter-${page}`}>
      {canSave && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => defaultFilterPref.write({ ...defaultFilterPref.read(), [page]: current })}
        >
          {t('common.default_filter_save', { defaultValue: 'Save as my default' })}
        </Button>
      )}
      {saved && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const rest = { ...defaultFilterPref.read() };
            delete rest[page];
            defaultFilterPref.write(rest);
          }}
        >
          {t('common.default_filter_clear', { defaultValue: 'Clear my default' })}
        </Button>
      )}
    </span>
  );
}
