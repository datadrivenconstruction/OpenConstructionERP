// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One control for "which cost line does this go on", wherever money is
// entered: contract lines, change order items, invoice lines, cost control.
// It lists the project's cost lines by code and name and searches as you type.
// Leaving it empty means "take what it inherits"; the caller says so in its
// placeholder.
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { SearchableSelect, type SearchableSelectOption } from '@/shared/ui/SearchableSelect';
import { costModelApi, type CostLine } from './api';

/** The API hands out at most this many lines per page. */
const PAGE = 200;
/** Enough pages for any real project; a larger one still finds its first lines. */
const MAX_PAGES = 15;

async function allLines(projectId: string): Promise<CostLine[]> {
  const out: CostLine[] = [];
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const batch = await costModelApi.getSpineLines(projectId, { offset: page * PAGE, limit: PAGE });
    out.push(...batch);
    if (batch.length < PAGE) break;
  }
  return out;
}

/** The project's cost lines, shared by every picker on the screen. */
export function useProjectCostLines(projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['spine-lines-all', projectId],
    queryFn: () => allLines(projectId!),
    enabled: enabled && !!projectId,
    staleTime: 60_000,
  });
}

/** "331 External walls" for a cost line id, or '' when it is not known. */
export function useCostLineLabel(projectId: string | null | undefined) {
  const lines = useProjectCostLines(projectId);
  return useMemo(() => {
    const byId = new Map((lines.data ?? []).map((l) => [l.id, `${l.code} ${l.description}`.trim()]));
    return (id: string | null | undefined) => (id ? (byId.get(id) ?? '') : '');
  }, [lines.data]);
}

export interface CostLinePickerProps {
  projectId: string;
  /** The chosen cost line id, or '' / null for none. */
  value: string | null | undefined;
  onChange: (costLineId: string) => void;
  /** Offer an empty choice; its label says what empty means here. */
  allowEmpty?: boolean;
  emptyLabel?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  'data-testid'?: string;
}

export function CostLinePicker({
  projectId,
  value,
  onChange,
  allowEmpty,
  emptyLabel,
  placeholder,
  disabled,
  className,
  id,
  'data-testid': testId,
}: CostLinePickerProps) {
  const { t } = useTranslation();
  const lines = useProjectCostLines(projectId);

  const options = useMemo<SearchableSelectOption[]>(() => {
    const list = (lines.data ?? [])
      .filter((l) => l.status !== 'closed' || l.id === value)
      .map((l) => ({
        value: l.id,
        label: `${l.code} ${l.description}`.trim(),
        keywords: `${l.code} ${l.description}`,
      }));
    // A line outside the loaded set still shows as chosen rather than as blank.
    if (value && !list.some((o) => o.value === value)) {
      list.unshift({
        value,
        label: t('costmodel.picker.unknown_line', { defaultValue: 'A cost line of this project' }),
        keywords: '',
      });
    }
    return list;
  }, [lines.data, value, t]);

  return (
    <SearchableSelect
      id={id}
      value={value ?? ''}
      onChange={onChange}
      options={options}
      allowEmpty={allowEmpty}
      emptyLabel={emptyLabel}
      loading={lines.isLoading}
      disabled={disabled || lines.isError}
      placeholder={placeholder ?? t('costmodel.picker.placeholder', { defaultValue: 'Choose a cost line' })}
      searchPlaceholder={t('costmodel.picker.search', { defaultValue: 'Find a code or name' })}
      className={className}
      data-testid={testId}
    />
  );
}
