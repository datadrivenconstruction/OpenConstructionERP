// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Documents & templates > Documents / Emails: every document or
 * email the enabled modules produce, with the state of the firm's wording.
 * A row opens the editor drawer in the chosen document language.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Search } from 'lucide-react';
import { Badge, Card, DateDisplay, EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import { listDocKinds, type Channel, type DocKindSummary } from './api';
import { DocTemplateEditor } from './DocTemplateEditor';
import { DOCUMENT_LANGUAGES, STATUS_VARIANT } from './docTemplateText';
import { DocumentManagersCard } from './DocumentManagersCard';
import { languageLabel, useKindLabel, useModuleLabel } from './labels';

export function DocTemplatesList({
  channel,
  initialKind,
  initialLanguage,
}: {
  channel: Channel;
  initialKind?: string | null;
  initialLanguage?: string;
}) {
  const { t, i18n } = useTranslation();
  const kindLabel = useKindLabel();
  const moduleLabel = useModuleLabel();
  const uiLang = (i18n.language || 'en').split('-')[0] ?? 'en';
  const [language, setLanguage] = useState<string>(initialLanguage || uiLang);
  const [search, setSearch] = useState('');
  const [module, setModule] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(initialKind ?? null);
  const q = useQuery({ queryKey: ['doc-templates', 'list'], queryFn: listDocKinds });

  const rows = useMemo(
    () => (q.data?.items ?? []).filter((r) => r.channel === channel),
    [q.data, channel],
  );
  const modules = useMemo(() => [...new Set(rows.map((r) => r.module))].sort(), [rows]);
  const visible = rows.filter((r) => {
    if (module && r.module !== module) return false;
    const needle = search.trim().toLowerCase();
    return !needle || kindLabel(r.key, r.label).toLowerCase().includes(needle) || r.key.includes(needle);
  });

  if (q.isLoading) {
    return (
      <Card padding="md" data-testid="doc-templates-loading">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="mb-2 h-9 w-full" />
        ))}
      </Card>
    );
  }
  if (q.isError) {
    return (
      <ErrorState
        title={t('settings.document_templates.load_failed', { defaultValue: 'Could not load document templates' })}
        onRetry={() => q.refetch()}
      />
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title={t('settings.document_templates.empty_no_modules', {
          defaultValue: 'No module that prints documents is active',
        })}
        action={
          <Link to="/settings?tab=modules" className="text-sm font-medium text-oe-blue hover:underline">
            {t('settings.document_templates.open_modules', { defaultValue: 'Open Modules' })}
          </Link>
        }
      />
    );
  }

  const statusLabel = (r: DocKindSummary) =>
    ({
      default: t('settings.document_templates.status_default', { defaultValue: 'Default' }),
      custom: t('settings.document_templates.status_custom', { defaultValue: 'Customised' }),
      draft: t('settings.document_templates.status_draft', { defaultValue: 'Draft not published' }),
      error: t('settings.document_templates.status_error', { defaultValue: 'Error' }),
    })[r.status];

  return (
    <div className="space-y-4" data-testid={`doc-templates-${channel}`}>
      <Card padding="md">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="oe-label">{t('settings.document_templates.language', { defaultValue: 'Language' })}</span>
            <select
              className="oe-input h-8 py-0"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              data-testid="doc-templates-language"
            >
              {DOCUMENT_LANGUAGES.map((code) => (
                <option key={code} value={code}>
                  {languageLabel(code, uiLang)}
                </option>
              ))}
            </select>
          </label>
          <div className="relative min-w-[200px] flex-1">
            <Search size={14} className="pointer-events-none absolute start-2.5 top-2.5 text-content-tertiary" />
            <input
              type="search"
              className="oe-input h-8 w-full ps-8"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('settings.document_templates.search', { defaultValue: 'Search' })}
              aria-label={t('settings.document_templates.search', { defaultValue: 'Search' })}
            />
          </div>
        </div>
        {modules.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {[null, ...modules].map((m) => (
              <button
                key={m ?? 'all'}
                type="button"
                onClick={() => setModule(m)}
                aria-pressed={module === m}
                className={clsx(
                  'rounded-full border px-2.5 py-0.5 text-xs',
                  module === m
                    ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                    : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {m ? moduleLabel(m) : t('settings.document_templates.all_modules', { defaultValue: 'All' })}
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card padding="none">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-start text-xs uppercase text-content-tertiary">
              <th className="px-4 py-2 text-start font-medium">
                {t('settings.document_templates.col_document', { defaultValue: 'Document' })}
              </th>
              <th className="px-4 py-2 text-start font-medium">
                {t('settings.document_templates.col_module', { defaultValue: 'Module' })}
              </th>
              <th className="px-4 py-2 text-start font-medium">
                {t('settings.document_templates.col_wording', { defaultValue: 'Wording' })}
              </th>
              <th className="px-4 py-2 text-start font-medium">
                {t('settings.document_templates.col_languages', { defaultValue: 'Languages' })}
              </th>
              <th className="px-4 py-2 text-start font-medium">
                {t('settings.document_templates.col_published', { defaultValue: 'Last published' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.key}
                tabIndex={0}
                role="button"
                onClick={() => setOpen(r.key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setOpen(r.key);
                  }
                }}
                className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary/60 focus:bg-surface-secondary/60 focus:outline-none"
                data-testid={`doc-template-row-${r.key}`}
              >
                <td className="px-4 py-2.5 font-medium text-content-primary">{kindLabel(r.key, r.label)}</td>
                <td className="px-4 py-2.5 text-content-secondary">{moduleLabel(r.module)}</td>
                <td className="px-4 py-2.5">
                  <span title={r.error_rules.join(', ') || undefined}>
                    <Badge variant={STATUS_VARIANT[r.status]} size="sm">
                      {statusLabel(r)}
                    </Badge>
                  </span>
                </td>
                <td className="px-4 py-2.5 text-content-secondary">
                  {r.languages.length === 0 ? '-' : r.languages.slice(0, 3).join(' ')}
                  {r.languages.length > 3 ? ` +${r.languages.length - 3}` : ''}
                </td>
                <td className="px-4 py-2.5 text-content-secondary">
                  {r.last_published_at ? (
                    <>
                      <DateDisplay value={r.last_published_at} format="numeric" /> {r.last_published_by}
                    </>
                  ) : (
                    '-'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {channel === 'pdf' && <DocumentManagersCard />}

      {open && (
        <DocTemplateEditor
          kindKey={open}
          initialLocale={language}
          canEdit={Boolean(q.data?.can_edit)}
          emailEnabled={Boolean(q.data?.email_enabled)}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}
