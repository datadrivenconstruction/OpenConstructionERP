// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Hourglass, ShieldCheck, ShieldAlert } from 'lucide-react';
import { Badge } from '@/shared/ui';
import {
  AGEING_BANDS,
  OVERDUE_BANDS,
  parsePct,
  type InterfaceRegister,
  type InterfaceRecord,
  type InterfaceValidationReport,
} from './api';

// English fallbacks for the computed `interface_management.ageing_band_*` keys.
const BAND_LABEL: Record<string, string> = {
  '0_7': '0-7 days',
  '8_30': '8-30 days',
  '31_60': '31-60 days',
  '61_90': '61-90 days',
  over_90: 'Over 90 days',
  over_60: 'Over 60 days',
  '1_7': '1-7 days',
};

// English fallbacks for the computed `interface_management.rule_*` keys. The
// backend message is English prose, so the screen names the rule from its id.
const RULE_LABEL: Record<string, string> = {
  schedule_activity_in_project: 'Schedule ID is not an activity of this project',
  rfi_in_project: 'Linked RFI is not an RFI of this project',
  agreed_has_agreed_date: 'Agreed without an agreed date',
  agreed_through_route: 'Agreed while its approval route is not approved',
  closed_was_agreed: 'Closed without being agreed first',
  need_by_before_activity_finish: 'Need-by date is after the linked activity finishes',
};

function BandBars({
  bands,
  counts,
  tone,
}: {
  bands: readonly string[];
  counts: Record<string, number>;
  tone: 'neutral' | 'error';
}) {
  const { t } = useTranslation();
  const max = Math.max(1, ...bands.map((b) => counts[b] ?? 0));
  return (
    <ul className="space-y-1">
      {bands.map((b) => {
        const n = counts[b] ?? 0;
        return (
          <li key={b} className="flex items-center gap-2 text-xs">
            <span className="w-24 shrink-0 text-content-tertiary">
              {t(`interface_management.ageing_band_${b}`, { defaultValue: BAND_LABEL[b] ?? b })}
            </span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-surface-secondary">
              <span
                className={clsx('block h-full rounded-full', tone === 'error' ? 'bg-semantic-error' : 'bg-oe-blue')}
                style={{ width: `${(n / max) * 100}%` }}
              />
            </span>
            <span className="w-6 shrink-0 text-end tabular-nums text-content-primary" data-testid={`band-${tone}-${b}`}>
              {n}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Register statistics that answer "how old is what is still open, and how late
 * is what is overdue": the open and overdue counts, the mean and oldest open
 * age, the worst lateness, and both ageing distributions. Below them, the
 * register checks (the ``interface_management`` rule set) as a traffic light,
 * each failing rule named per interface.
 */
export function RegisterAgeingPanel({
  register,
  validation,
  interfaces,
}: {
  register: InterfaceRegister | undefined;
  validation: InterfaceValidationReport | undefined;
  interfaces: InterfaceRecord[];
}) {
  const { t } = useTranslation();
  if (!register) return null;
  const avg = parsePct(register.average_open_age_days);
  const days = (n: number | null) =>
    n == null ? '-' : t('interface_management.days_count', { defaultValue: '{{count}} d', count: n });

  const refById = new Map(interfaces.map((i) => [i.id, i.reference]));
  const failing = (validation?.results ?? []).filter((r) => !r.passed);

  const tiles: { key: string; label: string; value: string; alert?: boolean }[] = [
    {
      key: 'open',
      label: t('interface_management.stat_open', { defaultValue: 'Open' }),
      value: String(register.open_count),
    },
    {
      key: 'overdue',
      label: t('interface_management.stat_overdue', { defaultValue: 'Overdue' }),
      value: String(register.overdue_count),
      alert: register.overdue_count > 0,
    },
    {
      key: 'avg',
      label: t('interface_management.stat_avg_age', { defaultValue: 'Average open age' }),
      value: avg == null ? '-' : days(Math.round(avg)),
    },
    {
      key: 'oldest',
      label: t('interface_management.stat_oldest_open', { defaultValue: 'Oldest open' }),
      value: days(register.oldest_open_age_days),
    },
    {
      key: 'late',
      label: t('interface_management.stat_max_overdue', { defaultValue: 'Most days overdue' }),
      value: days(register.max_days_overdue),
      alert: (register.max_days_overdue ?? 0) > 0,
    },
  ];

  return (
    <section className="rounded-xl border border-border bg-surface-elevated shadow-sm p-4" data-testid="register-ageing">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Hourglass size={15} className="text-oe-blue" />
        {t('interface_management.ageing_title', { defaultValue: 'Register ageing' })}
      </h2>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {tiles.map((tile) => (
          <div key={tile.key} className="rounded-lg bg-surface-primary/70 px-3 py-2">
            <p
              className={clsx(
                'text-base font-semibold tabular-nums',
                tile.alert ? 'text-semantic-error' : 'text-content-primary',
              )}
              data-testid={`ageing-tile-${tile.key}`}
            >
              {tile.value}
            </p>
            <p className="text-2xs text-content-tertiary">{tile.label}</p>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <p className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('interface_management.ageing_open_by_age', { defaultValue: 'Open interfaces by age' })}
          </p>
          <BandBars bands={AGEING_BANDS} counts={register.ageing} tone="neutral" />
        </div>
        <div>
          <p className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('interface_management.ageing_overdue_by_days', { defaultValue: 'Overdue interfaces by days late' })}
          </p>
          <BandBars bands={OVERDUE_BANDS} counts={register.overdue_ageing} tone="error" />
        </div>
      </div>

      {validation && (
        <div className="mt-4 border-t border-border-light pt-3" data-testid="register-checks">
          <div className="flex flex-wrap items-center gap-2">
            {failing.length === 0 ? (
              <ShieldCheck size={15} className="text-semantic-success" />
            ) : (
              <ShieldAlert size={15} className={validation.errors > 0 ? 'text-semantic-error' : 'text-semantic-warning'} />
            )}
            <span className="text-sm font-semibold text-content-primary">
              {t('interface_management.checks_title', { defaultValue: 'Register checks' })}
            </span>
            <Badge variant={validation.errors > 0 ? 'error' : 'neutral'} size="sm">
              {t('interface_management.checks_errors', { defaultValue: '{{count}} errors', count: validation.errors })}
            </Badge>
            <Badge variant={validation.warnings > 0 ? 'warning' : 'neutral'} size="sm">
              {t('interface_management.checks_warnings', {
                defaultValue: '{{count}} warnings',
                count: validation.warnings,
              })}
            </Badge>
          </div>
          {failing.length === 0 ? (
            <p className="mt-1 text-xs text-content-tertiary">
              {t('interface_management.checks_all_passed', {
                defaultValue: 'Links, dates and approvals are consistent.',
              })}
            </p>
          ) : (
            <ul className="mt-2 space-y-1">
              {failing.map((r, idx) => {
                const short = r.rule_id.replace(/^interface_management\./, '');
                return (
                  <li key={`${r.rule_id}-${r.element_ref ?? idx}`} className="flex items-center gap-2 text-xs">
                    <Badge variant={r.severity === 'error' ? 'error' : 'warning'} size="sm">
                      {(r.element_ref && refById.get(r.element_ref)) || '-'}
                    </Badge>
                    <span className="text-content-secondary">
                      {t(`interface_management.rule_${short}`, { defaultValue: RULE_LABEL[short] ?? short })}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
