// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Small presentational pieces shared by the guarantees pages. */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CheckCircle2, AlertTriangle, XCircle, Landmark } from 'lucide-react';
import { CollapsibleSection } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import type { AlertBand, GuaranteeFinding } from './api';
import { alertBandClass } from './api';
import { ruleLabel } from './labels';

export const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
export const selectCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
export const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

export function Money({ value, currency }: { value: string | null | undefined; currency: string }) {
  if (value === null || value === undefined || value === '') return <span>—</span>;
  return <span className="tabular-nums">{formatCurrency(value, currency)}</span>;
}

/** Expiry countdown chip: red within 14 days, amber within 30, yellow within 60. */
export function AlertBadge({ band, days }: { band: AlertBand | null; days: number | null }) {
  const { t } = useTranslation();
  if (days === null) return null;
  const text =
    days < 0
      ? t('guarantees.expired_days_ago', { defaultValue: 'expired {{count}} d ago', count: Math.abs(days) })
      : t('guarantees.days_left', { defaultValue: '{{count}} d left', count: days });
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium',
        days < 0 ? 'bg-rose-100 text-rose-700' : alertBandClass(band),
      )}
    >
      {text}
    </span>
  );
}

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function GuaranteesExplainer() {
  const { t } = useTranslation();
  const steps = [
    {
      title: t('guarantees.flow_1_title', { defaultValue: 'Register' }),
      desc: t('guarantees.flow_1_desc', { defaultValue: 'Record the guarantee with its bank, amount and expiry date.' }),
    },
    {
      title: t('guarantees.flow_2_title', { defaultValue: 'Issue and link' }),
      desc: t('guarantees.flow_2_desc', { defaultValue: 'Mark it issued and attach the contract and the bank original.' }),
    },
    {
      title: t('guarantees.flow_3_title', { defaultValue: 'Watch expiry' }),
      desc: t('guarantees.flow_3_desc', { defaultValue: 'Get alerted at 60, 30 and 14 days to extend or plan the release.' }),
    },
    {
      title: t('guarantees.flow_4_title', { defaultValue: 'Release or call' }),
      desc: t('guarantees.flow_4_desc', { defaultValue: 'Close it out as released, called or expired and keep the history.' }),
    },
  ];
  return (
    <CollapsibleSection
      storageKey="guarantees.how"
      icon={<Landmark size={15} className="text-oe-blue" />}
      title={t('guarantees.flow_title', { defaultValue: 'How guarantees work, and what they connect to' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('guarantees.flow_intro', {
          defaultValue:
            'Keep every bank guarantee and bond in one register so nothing lapses unnoticed and you always know how much of your credit lines is tied up.',
        })}
      </p>
      <ol className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s.title} className="rounded-lg border border-border-light bg-surface-primary p-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-xs font-semibold text-oe-blue">
                {i + 1}
              </span>
              <span className="text-xs font-semibold text-content-primary">{s.title}</span>
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('guarantees.flow_connects', { defaultValue: 'Connects with:' })}
        </span>{' '}
        <ModLink to="/contracts">{t('guarantees.mod_contracts', { defaultValue: 'Contracts' })}</ModLink>
        {' · '}
        <ModLink to="/tendering">{t('guarantees.mod_tendering', { defaultValue: 'Tendering' })}</ModLink>
        {' · '}
        <ModLink to="/subcontractors">{t('guarantees.mod_subcontractors', { defaultValue: 'Subcontractors' })}</ModLink>
        {' · '}
        <ModLink to="/finance">{t('guarantees.mod_finance', { defaultValue: 'Finance' })}</ModLink>
        {' · '}
        <ModLink to="/documents">{t('guarantees.mod_documents', { defaultValue: 'Documents' })}</ModLink>
      </div>
    </CollapsibleSection>
  );
}

/** Traffic light over the validation findings: green when empty, amber or red otherwise. */
export function ValidationBlock({ findings }: { findings: GuaranteeFinding[] }) {
  const { t } = useTranslation();
  const hasError = findings.some((f) => f.severity === 'error');
  const tone = findings.length === 0 ? 'ok' : hasError ? 'error' : 'warn';
  const Icon = tone === 'ok' ? CheckCircle2 : tone === 'error' ? XCircle : AlertTriangle;
  return (
    <div
      data-testid="guarantees-validation"
      className={clsx(
        'rounded-xl border p-3',
        tone === 'ok' && 'border-emerald-200 bg-emerald-50',
        tone === 'warn' && 'border-amber-200 bg-amber-50',
        tone === 'error' && 'border-rose-200 bg-rose-50',
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <Icon
          size={16}
          className={clsx(tone === 'ok' && 'text-emerald-600', tone === 'warn' && 'text-amber-600', tone === 'error' && 'text-rose-600')}
        />
        {findings.length === 0
          ? t('guarantees.validation_ok', { defaultValue: 'All guarantee checks pass' })
          : t('guarantees.validation_findings', {
              defaultValue: '{{count}} guarantee checks need attention',
              count: findings.length,
            })}
      </div>
      {findings.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {findings.map((f, i) => (
            <li key={`${f.rule_id}-${f.element_ref ?? i}`} className="text-xs">
              <span className="font-medium text-content-primary">{ruleLabel(t, f.rule_id)}</span>
              <span className="text-content-secondary"> · {f.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
