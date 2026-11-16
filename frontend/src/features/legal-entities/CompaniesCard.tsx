// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Companies and sites", the first card of Settings > Company & documents.
 *
 * Each project belongs to one company, whose name and tax id print on its
 * invoices. With one company the card is a single calm line; the table, and
 * every company picker elsewhere, appear only once a second company exists.
 * Everyone reads it; only an admin opens the drawer to edit.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Building2, Plus } from 'lucide-react';
import clsx from 'clsx';

import { Badge, Button, Card, EmptyState, ErrorState, SkeletonTable } from '@/shared/ui';

import type { LegalEntity } from './api';
import { CompanyDrawer } from './CompanyDrawer';
import { useCompanies } from './useCompanies';

export function CompaniesCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const companiesQ = useCompanies();
  // `new` opens an empty drawer; an id opens that company.
  const [open, setOpen] = useState<string | null>(null);

  const companies = companiesQ.data ?? [];
  const active = companies.filter((c) => c.is_active);
  const openCompany = companies.find((c) => c.id === open) ?? null;

  const status = (c: LegalEntity) =>
    c.is_default ? (
      <Badge variant="blue" size="sm">{t('legal_entities.status_default', { defaultValue: 'Default' })}</Badge>
    ) : c.is_active ? (
      <Badge variant="success" size="sm">{t('legal_entities.status_active', { defaultValue: 'Active' })}</Badge>
    ) : (
      <Badge variant="neutral" size="sm">{t('legal_entities.status_inactive', { defaultValue: 'Inactive' })}</Badge>
    );

  let body;
  if (companiesQ.isLoading) {
    body = <SkeletonTable rows={2} columns={7} />;
  } else if (companiesQ.isError) {
    body = (
      <ErrorState
        compact
        title={t('legal_entities.load_failed', { defaultValue: 'Could not load the companies' })}
        onRetry={() => companiesQ.refetch()}
      />
    );
  } else if (companies.length === 0) {
    body = (
      <EmptyState
        icon={<Building2 size={20} />}
        title={t('legal_entities.empty_title', { defaultValue: 'No company yet' })}
        description={t('legal_entities.empty_hint', {
          defaultValue: 'Add the company that signs your contracts and invoices.',
        })}
        action={
          canEdit ? (
            <Button size="sm" icon={<Plus size={14} />} onClick={() => setOpen('new')}>
              {t('legal_entities.add', { defaultValue: 'Add company' })}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (active.length === 1 && companies.length === 1) {
    const only = companies[0]!;
    body = (
      <div className="flex flex-wrap items-center gap-3 text-sm text-content-secondary" data-testid="companies-only-one">
        <button
          type="button"
          className="text-start text-content-primary hover:underline"
          onClick={() => setOpen(only.id)}
          aria-label={t('legal_entities.open_company', { defaultValue: 'Open {{company}}', company: only.name })}
        >
          {t('legal_entities.only_one', { defaultValue: '{{name}} is your only company.', name: only.legal_name || only.name })}
        </button>
        {canEdit && (
          <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setOpen('new')}>
            {t('legal_entities.add_another', { defaultValue: 'Add another company' })}
          </Button>
        )}
      </div>
    );
  } else {
    body = (
      <div className="overflow-x-auto">
        <table className="oe-table w-full" data-testid="companies-table">
          <thead>
            <tr>
              <th>{t('legal_entities.col_code', { defaultValue: 'Code' })}</th>
              <th>{t('legal_entities.col_company', { defaultValue: 'Company' })}</th>
              <th>{t('legal_entities.col_country', { defaultValue: 'Country' })}</th>
              <th>{t('legal_entities.col_tax_id', { defaultValue: 'Tax id' })}</th>
              <th className="text-end">{t('legal_entities.col_sites', { defaultValue: 'Sites' })}</th>
              <th className="text-end">{t('legal_entities.col_projects', { defaultValue: 'Projects' })}</th>
              <th>{t('legal_entities.col_status', { defaultValue: 'Status' })}</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((c) => (
              <tr
                key={c.id}
                className={clsx('cursor-pointer', !c.is_active && 'opacity-60')}
                onClick={() => setOpen(c.id)}
              >
                <td>
                  <button
                    type="button"
                    className="font-mono text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen(c.id);
                    }}
                    aria-label={t('legal_entities.open_company', { defaultValue: 'Open {{company}}', company: c.name })}
                  >
                    <bdi>{c.code}</bdi>
                  </button>
                </td>
                <td className="text-content-primary">{c.legal_name || c.name}</td>
                <td>{c.country_code}</td>
                <td className="font-mono text-xs">
                  <bdi>{c.primary_tax_id}</bdi>
                </td>
                <td className="text-end tabular-nums">{c.branches.length}</td>
                <td className="text-end tabular-nums">
                  <Link
                    to={`/projects?company=${encodeURIComponent(c.id)}`}
                    className="text-oe-blue hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {c.project_count}
                  </Link>
                </td>
                <td>{status(c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <Card padding="md" data-testid="companies-card">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Building2 size={16} className="mt-0.5 shrink-0 text-content-tertiary" />
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('legal_entities.title', { defaultValue: 'Companies and sites' })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('legal_entities.intro', {
                defaultValue: 'Each project belongs to one company. Its name and tax id print on invoices.',
              })}
            </p>
          </div>
        </div>
        {canEdit && companies.length > 1 && (
          <Button size="sm" icon={<Plus size={14} />} onClick={() => setOpen('new')}>
            {t('legal_entities.add', { defaultValue: 'Add company' })}
          </Button>
        )}
      </div>
      {body}
      {open !== null && (
        <CompanyDrawer
          company={open === 'new' ? null : openCompany}
          isFirst={companies.length === 0}
          canEdit={canEdit}
          onClose={() => setOpen(null)}
        />
      )}
    </Card>
  );
}
