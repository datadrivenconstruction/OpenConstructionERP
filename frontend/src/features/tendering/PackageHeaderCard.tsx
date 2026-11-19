// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Package header: who buys (company), what (trade, cost line, budget), when
 * (four dates) and who does it (four roles). The company picker appears only
 * from two active companies; with one, letters simply carry that company.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, Card, Input, SearchableSelect } from '@/shared/ui';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { costModelApi } from '@/features/costmodel/api';
import { useCompanies } from '@/features/legal-entities/useCompanies';

import { getPackageHeader, savePackageHeader } from './api';
import {
  HEADER_DATE_FIELDS,
  HEADER_ROLE_FIELDS,
  dateOrderWarnings,
  headerChanges,
  headerForm,
  type HeaderForm,
} from './awardFlow';

interface Props {
  packageId: string;
  projectId: string;
  deadline?: string | null;
  /** Awarded or closed: company and cost line are fixed, the rest stays open. */
  locked: boolean;
}

export function PackageHeaderCard({ packageId, projectId, deadline, locked }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['tendering', 'header', packageId];
  const headerQ = useQuery({ queryKey: key, queryFn: () => getPackageHeader(packageId) });
  const header = headerQ.data;
  const multiCompany = (header?.active_entity_count ?? 0) >= 2;
  const companiesQ = useCompanies(multiCompany);
  const linesQ = useQuery({
    queryKey: ['costmodel', 'spine-lines', projectId, 'picker'],
    queryFn: () => costModelApi.getSpineLines(projectId, { limit: 200 }),
    staleTime: 60_000,
    retry: false,
  });

  const saved = useMemo(() => headerForm(header, deadline), [header, deadline]);
  const [form, setForm] = useState<HeaderForm>(saved);
  useEffect(() => setForm(saved), [saved]);
  const set = (k: keyof HeaderForm, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const changes = headerChanges(saved, form);
  const dirty = Object.keys(changes).length > 0;
  const warnings = dateOrderWarnings(form);

  const saveM = useMutation({
    mutationFn: () => savePackageHeader(packageId, changes),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      qc.invalidateQueries({ queryKey: ['tendering', 'rejections', packageId] });
      addToast({ type: 'success', title: t('tendering.header.saved', { defaultValue: 'Package header saved' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (headerQ.isLoading || !header) return null;
  const currency = header.currency;
  const companies = (companiesQ.data ?? []).filter((c) => c.is_active || c.id === form.legal_entity_id);
  const lineOptions = (linesQ.data ?? []).map((l) => ({
    value: l.id,
    label: l.description || l.code,
    hint: l.code,
  }));

  const dateLabel: Record<(typeof HEADER_DATE_FIELDS)[number], string> = {
    issue_date: t('tendering.header.issue_date', { defaultValue: 'Issued' }),
    questions_until: t('tendering.header.questions_until', { defaultValue: 'Questions until' }),
    bids_due: t('tendering.header.bids_due', { defaultValue: 'Bids due' }),
    award_planned: t('tendering.header.award_planned', { defaultValue: 'Award planned' }),
  };
  const roleLabel: Record<(typeof HEADER_ROLE_FIELDS)[number], string> = {
    buyer_id: t('tendering.header.buyer', { defaultValue: 'Buyer' }),
    estimator_id: t('tendering.header.estimator', { defaultValue: 'Estimator' }),
    site_manager_id: t('tendering.header.site_manager', { defaultValue: 'Site manager' }),
    approver_id: t('tendering.header.approver', { defaultValue: 'Approver' }),
  };
  return (
    <Card className="mb-3" data-testid="package-header">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-content-primary">
            {t('tendering.header.title', { defaultValue: 'Package header' })}
          </h4>
          {header.issuing_entity && (
            <p className="text-xs text-content-secondary" data-testid="package-header-issuer">
              {t('tendering.header.issued_in', {
                defaultValue: 'Letters and the contract are issued by {{company}}',
                company: header.issuing_entity.name,
              })}
            </p>
          )}
        </div>
        <Button size="sm" disabled={!dirty || saveM.isPending} onClick={() => saveM.mutate()}>
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {multiCompany && (
          <label className="block text-sm" data-testid="package-header-company">
            <span className="mb-1 block font-medium text-content-primary">
              {t('tendering.header.company', { defaultValue: 'Company (client entity)' })}
            </span>
            <select
              className="oe-select w-full"
              value={form.legal_entity_id}
              disabled={locked}
              onChange={(e) => set('legal_entity_id', e.target.value)}
            >
              <option value="">
                {t('tendering.header.company_from_project', { defaultValue: "Project's company" })}
              </option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.legal_name || c.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <Input
          label={t('tendering.header.trade', { defaultValue: 'Trade' })}
          value={form.trade}
          maxLength={120}
          onChange={(e) => set('trade', e.target.value)}
        />
        <div className="text-sm">
          <span className="mb-1 block font-medium text-content-primary">
            {t('tendering.header.cost_line', { defaultValue: 'Cost code' })}
          </span>
          <SearchableSelect
            value={form.cost_line_id}
            onChange={(v) => set('cost_line_id', v)}
            options={lineOptions}
            allowEmpty
            loading={linesQ.isLoading}
            disabled={locked}
            data-testid="package-header-cost-line"
          />
        </div>
        <div className="text-sm">
          <span className="mb-1 block font-medium text-content-primary">
            {t('tendering.header.budget', { defaultValue: 'Budget' })}
          </span>
          <p className="py-1.5 tabular-nums text-content-primary" data-testid="package-header-budget">
            {fmtCurrency(header.cost_line?.budget ?? header.budget, currency)}
          </p>
        </div>
        {HEADER_DATE_FIELDS.map((k) => (
          <Input
            key={k}
            type="date"
            label={dateLabel[k]}
            value={form[k]}
            onChange={(e) => set(k, e.target.value)}
          />
        ))}
        {HEADER_ROLE_FIELDS.map((k) => (
          <div key={k} className="text-sm">
            <span className="mb-1 block font-medium text-content-primary">{roleLabel[k]}</span>
            <ProjectPeopleSelect value={form[k]} onChange={(id) => set(k, id)} projectId={projectId} />
          </div>
        ))}
      </div>
      {warnings.length > 0 && (
        <ul className="mt-2 text-xs text-semantic-warning" data-testid="package-header-warnings">
          <li>
            {t('tendering.header.dates_out_of_order', {
              defaultValue: 'The dates are out of order: issue, questions, bids due, award.',
            })}
          </li>
        </ul>
      )}
    </Card>
  );
}
