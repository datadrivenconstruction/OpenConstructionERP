// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One picker over the two company registers: subcontractors and vendors. A
// bidder candidate and the supplier of a framework agreement are both "a
// registered company", so they share it. The value is `subcontractor:id`,
// `vendor:id`, or empty for a company that is not registered yet.
//
// Neither register route takes a search term, and both hand out at most 200
// rows a page. So the picker reads the pages one after the other and narrows
// the list by name in the browser. A register larger than the page budget is
// said to be cut short, with the number of companies left out.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { listSubcontractors } from '@/features/subcontractors/api';
import { listVendors } from '@/features/supplier-catalogs/api';

import { FIELD_CLASS, Field } from './ProcurementBits';

export interface RegisteredCompany {
  value: string;
  name: string;
}

/** The most rows one request may ask for; both register routes refuse more. */
export const REGISTER_PAGE = 200;
/** How many pages of one register the picker reads before it says the list is cut short. */
export const REGISTER_MAX_PAGES = 10;
/** From this many companies on, the picker offers a name filter. */
const FILTER_FROM = 12;

interface RegisterPage<T> {
  items: T[];
  total?: number;
}

/** Every page of one register, up to the page budget. `missing` counts the rows the budget left out. */
export async function readRegister<T>(
  page: (offset: number, limit: number) => Promise<RegisterPage<T>>,
): Promise<{ items: T[]; missing: number }> {
  const items: T[] = [];
  let total = 0;
  for (let n = 0; n < REGISTER_MAX_PAGES; n += 1) {
    const got = await page(n * REGISTER_PAGE, REGISTER_PAGE);
    items.push(...got.items);
    total = Math.max(got.total ?? 0, items.length);
    if (got.items.length < REGISTER_PAGE || items.length >= total) break;
  }
  return { items, missing: Math.max(0, total - items.length) };
}

/** The companies whose name holds every word of the filter, whatever the case. */
export function filterCompanies(companies: RegisteredCompany[], filter: string): RegisteredCompany[] {
  const words = filter.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return companies;
  return companies.filter((c) => {
    const name = c.name.toLocaleLowerCase();
    return words.every((w) => name.includes(w));
  });
}

/** Both registers, read once the form that needs them is open. */
export function useCompanyRegister(enabled: boolean) {
  const subcontractorsQ = useQuery({
    queryKey: ['procurement-concept-company', 'subcontractors'],
    queryFn: () => readRegister((offset, limit) => listSubcontractors({ offset, limit, active_only: true })),
    enabled,
    staleTime: 60_000,
  });
  const vendorsQ = useQuery({
    queryKey: ['procurement-concept-company', 'vendors'],
    queryFn: () => readRegister((offset, limit) => listVendors({ status: 'active', offset, limit })),
    enabled,
    staleTime: 60_000,
  });
  const subcontractors: RegisteredCompany[] = (subcontractorsQ.data?.items ?? []).map((s) => ({
    value: `subcontractor:${s.id}`,
    name: s.trade_name || s.legal_name,
  }));
  const vendors: RegisteredCompany[] = (vendorsQ.data?.items ?? []).map((v) => ({ value: `vendor:${v.id}`, name: v.name }));
  return {
    subcontractors,
    vendors,
    loading: subcontractorsQ.isLoading || vendorsQ.isLoading,
    /** One register could not be read, so the list may miss companies. */
    partial: subcontractorsQ.isError || vendorsQ.isError,
    /** Companies the registers hold beyond what was read. */
    missing: (subcontractorsQ.data?.missing ?? 0) + (vendorsQ.data?.missing ?? 0),
    nameOf: (value: string) => [...subcontractors, ...vendors].find((c) => c.value === value)?.name ?? null,
  };
}

export function CompanyPicker({
  id,
  label,
  value,
  keptName,
  register,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  /** The name of the linked company when it is not among the ones the registers list now. */
  keptName?: string;
  register: ReturnType<typeof useCompanyRegister>;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState('');
  const { loading, partial, missing } = register;
  const count = register.subcontractors.length + register.vendors.length;
  // The chosen company stays in the list whatever the filter says, so the select never shows a blank.
  const keep = (list: RegisteredCompany[]) => {
    const shown = filterCompanies(list, filter);
    const chosen = list.find((c) => c.value === value);
    return chosen && !shown.includes(chosen) ? [chosen, ...shown] : shown;
  };
  const subcontractors = keep(register.subcontractors);
  const vendors = keep(register.vendors);
  const known = register.subcontractors.some((c) => c.value === value) || register.vendors.some((c) => c.value === value);
  const hint = loading
    ? t('procurement_concept.ui.candidate.company_loading', { defaultValue: 'Reading the subcontractor and vendor registers' })
    : partial
      ? t('procurement_concept.ui.candidate.company_partial', {
          defaultValue: 'Part of the company register could not be read, so this list may be incomplete.',
        })
      : missing > 0
        ? t('procurement_concept.ui.candidate.company_cut', {
            defaultValue:
              'The registers hold more companies than this list can read: {{n}} are not shown. If the company is missing, open it in the subcontractor or vendor register to check its name, or type the name below.',
            n: missing,
          })
        : count === 0
          ? t('procurement_concept.ui.candidate.company_none', {
              defaultValue: 'No subcontractor or vendor is registered yet. Type the company name instead.',
            })
          : filter.trim() && subcontractors.length + vendors.length === (known ? 1 : 0)
            ? t('procurement_concept.ui.candidate.company_no_match', { defaultValue: 'No registered company has this in its name.' })
            : undefined;
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      {count >= FILTER_FROM && (
        <input
          type="search"
          className={`${FIELD_CLASS} mb-1.5`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label={t('procurement_concept.ui.candidate.company_filter', { defaultValue: 'Narrow the list by name' })}
          placeholder={t('procurement_concept.ui.candidate.company_filter', { defaultValue: 'Narrow the list by name' })}
          data-testid="company-filter"
        />
      )}
      <select id={id} className={FIELD_CLASS} value={value} aria-busy={loading} onChange={(e) => onChange(e.target.value)} data-testid="company-picker">
        <option value="">{t('procurement_concept.ui.candidate.not_registered', { defaultValue: 'Not registered yet' })}</option>
        {value && !known && (
          <option value={value}>{keptName || t('procurement_concept.ui.candidate.company_kept', { defaultValue: 'The company linked before' })}</option>
        )}
        {subcontractors.length > 0 && (
          <optgroup label={t('procurement_concept.ui.candidate.group_subcontractors', { defaultValue: 'Subcontractors' })}>
            {subcontractors.map((c) => (
              <option key={c.value} value={c.value}>
                {c.name}
              </option>
            ))}
          </optgroup>
        )}
        {vendors.length > 0 && (
          <optgroup label={t('procurement_concept.ui.candidate.group_vendors', { defaultValue: 'Vendors' })}>
            {vendors.map((c) => (
              <option key={c.value} value={c.value}>
                {c.name}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </Field>
  );
}
