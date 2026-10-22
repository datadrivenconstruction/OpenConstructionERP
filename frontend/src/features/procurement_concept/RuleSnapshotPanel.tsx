// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The rules a procedure was set under, as they were that day. Read-only: a
// later change to the catalogue or the package never reaches this record.
// Overrides of a rule outcome are listed with their reason, who and when.

import { useTranslation } from 'react-i18next';

import { fmtDate } from '@/shared/lib/formatters';

import type { RuleOutcome } from './api';
import { useRuleSnapshots } from './hooks';
import { RefusalBox, ToneBadge } from './ProcurementBits';

const OUTCOME_TONE: Record<RuleOutcome, 'success' | 'warning' | 'error'> = {
  pass: 'success',
  warn: 'warning',
  fail: 'error',
};

export function RuleSnapshotPanel({ projectId, packageId }: { projectId: string; packageId: string | null }) {
  const { t } = useTranslation();
  const q = useRuleSnapshots(projectId, packageId);
  const snapshots = q.data?.items ?? [];
  const outcome = (o: RuleOutcome) => t(`procurement_concept.ui.snapshot.outcome_${o}`, { defaultValue: o });
  const rule = (code: string) =>
    t(`procurement_concept.ui.snapshot.rule_${code}`, { defaultValue: code.replace(/_/g, ' ') });

  return (
    <section data-testid="rule-snapshot-section">
      <h3 className="mb-1 text-sm font-semibold text-content-primary">
        {t('procurement_concept.ui.snapshot.title', { defaultValue: 'Rules applied when the procedure was set' })}
      </h3>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('procurement_concept.ui.snapshot.hint', {
          defaultValue: 'A frozen record. A later change to the catalogue or to this package does not alter it.',
        })}
      </p>
      {q.isError ? (
        <RefusalBox error={q.error} />
      ) : snapshots.length === 0 ? (
        <p className="rounded-md bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="rule-snapshot-empty">
          {t('procurement_concept.ui.snapshot.none', { defaultValue: 'No record yet. It is taken when a procedure is set.' })}
        </p>
      ) : (
        <div className="space-y-3">
          {snapshots.map((s) => (
            <div key={s.id} className="rounded-lg border border-border-light p-3 text-sm" data-testid="rule-snapshot">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-content-primary">{s.procedure_code}</span>
                <span className="text-content-tertiary">
                  {t('procurement_concept.ui.snapshot.taken', {
                    defaultValue: 'Taken {{date}}, rules as of {{checked}}',
                    date: s.taken_at ? fmtDate(s.taken_at) : '',
                    checked: fmtDate(s.checked_on),
                  })}
                </span>
                {s.catalogue.review_status && s.catalogue.review_status !== 'verified' && (
                  <ToneBadge tone="warning" testId="rule-snapshot-unconfirmed">
                    {t('procurement_concept.ui.snapshot.unconfirmed', { defaultValue: 'Catalogue not yet confirmed' })}
                  </ToneBadge>
                )}
                {!s.integrity_ok && (
                  <ToneBadge tone="error" testId="rule-snapshot-altered">
                    {t('procurement_concept.ui.snapshot.altered', { defaultValue: 'Record does not match its seal' })}
                  </ToneBadge>
                )}
              </div>
              <p className="mt-1 text-xs text-content-tertiary">
                {t('procurement_concept.ui.snapshot.catalogue', {
                  defaultValue: 'Catalogue {{id}} version {{version}} ({{source}})',
                  id: s.catalogue.id,
                  version: s.catalogue.version,
                  source: s.catalogue.source,
                })}
              </p>
              <ul className="mt-2 flex flex-wrap gap-2" data-testid="rule-snapshot-outcomes">
                {s.result.outcomes.map((o) => (
                  <li key={o.rule_code}>
                    <ToneBadge tone={OUTCOME_TONE[o.outcome]}>
                      {rule(o.rule_code)}: {outcome(o.outcome)}
                    </ToneBadge>
                  </li>
                ))}
              </ul>
              <table className="mt-2 w-full text-left text-xs" data-testid="rule-snapshot-rules">
                <thead>
                  <tr className="text-content-tertiary">
                    <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.snapshot.th_rule', { defaultValue: 'Rule' })}</th>
                    <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.snapshot.th_figure', { defaultValue: 'Figure' })}</th>
                    <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.snapshot.th_valid', { defaultValue: 'In force' })}</th>
                    <th className="py-1 font-medium">{t('procurement_concept.ui.snapshot.th_source', { defaultValue: 'Source' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {s.rules.map((r) => (
                    <tr key={r.id} className="border-t border-border-light align-top">
                      <td className="py-1 pr-3 text-content-secondary">{r.id}</td>
                      <td className="py-1 pr-3">{r.amount ? `${r.amount} ${r.currency ?? ''}` : ''}</td>
                      <td className="py-1 pr-3">
                        {r.valid_from ? fmtDate(r.valid_from) : ''}
                        {r.valid_to ? ` - ${fmtDate(r.valid_to)}` : ''}
                      </td>
                      <td className="py-1">
                        {r.source_url ? (
                          <a href={r.source_url} target="_blank" rel="noreferrer noopener" className="text-oe-blue underline">
                            {r.review_status === 'verified'
                              ? t('procurement_concept.ui.snapshot.source_verified', { defaultValue: 'Confirmed' })
                              : t('procurement_concept.ui.snapshot.source_unconfirmed', { defaultValue: 'Not yet confirmed' })}
                          </a>
                        ) : r.kind === 'procedure' ? null : (
                          t('procurement_concept.ui.snapshot.source_missing', { defaultValue: 'No source given' })
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {s.overrides.length > 0 && (
                <div className="mt-2" data-testid="rule-snapshot-overrides">
                  <h4 className="text-xs font-semibold text-content-primary">
                    {t('procurement_concept.ui.snapshot.overrides', { defaultValue: 'Manual overrides' })}
                  </h4>
                  <ul className="mt-1 space-y-1">
                    {s.overrides.map((o) => (
                      <li key={o.id} className="text-xs text-content-secondary">
                        {t('procurement_concept.ui.snapshot.override_line', {
                          defaultValue: '{{rule}}: {{from}} to {{to}} on {{date}}. Reason: {{reason}}',
                          rule: rule(o.rule_code),
                          from: outcome(o.original_outcome),
                          to: outcome(o.override_outcome),
                          date: o.overridden_at ? fmtDate(o.overridden_at) : '',
                          reason: o.reason,
                        })}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
