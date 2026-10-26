// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DocumentLanguageSelect - the language choice of a document.
 *
 * Every language is listed under its own name; the English name and the code
 * are searchable too, so a list of forty languages is a type-ahead and not a
 * scroll. One component for every screen that prints a document in a language
 * the reader picks: the export menu, the property-development document
 * preview, the contract form.
 */
import { useMemo } from 'react';

import { documentLocaleEnglishName, documentLocaleName } from '@/shared/lib/documentExport';
import { SearchableSelect } from '@/shared/ui/SearchableSelect';

export interface DocumentLanguageSelectProps {
  value: string;
  onChange: (locale: string) => void;
  /** Languages the document exists in. */
  locales: readonly string[];
  id?: string;
  disabled?: boolean;
  className?: string;
  'data-testid'?: string;
}

export function DocumentLanguageSelect({
  value,
  onChange,
  locales,
  id,
  disabled,
  className,
  'data-testid': testId,
}: DocumentLanguageSelectProps) {
  const options = useMemo(
    () =>
      locales.map((code) => ({
        value: code,
        label: documentLocaleName(code),
        hint: code,
        keywords: documentLocaleEnglishName(code),
      })),
    [locales],
  );
  return (
    <SearchableSelect
      value={value}
      onChange={onChange}
      options={options}
      searchThreshold={0}
      id={id}
      disabled={disabled}
      className={className}
      data-testid={testId}
    />
  );
}
