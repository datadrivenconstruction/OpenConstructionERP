// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rule results​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ list: a traffic-light tally plus one line per failed rule.
 * Shared by the equipment telematics tab and the site sensors page.
 */
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  failedRules,
  ruleLight,
  ruleMessage,
  tallyRules,
  type RuleResult,
  type TrafficLight,
} from '@/shared/lib/ruleResults';

const DOT: Record<TrafficLight, string> = {
  red: 'bg-semantic-error',
  amber: 'bg-semantic-warning',
  blue: 'bg-oe-blue',
  green: 'bg-semantic-success',
};

export function LightDot({ light, className }: { light: TrafficLight; className?: string }) {
  return <span aria-hidden="true" className={clsx('inline-block h-2.5 w-2.5 shrink-0 rounded-full', DOT[light], className)} />;
}

export function RuleResultsList({ results }: { results: readonly RuleResult[] }) {
  const { t } = useTranslation();
  const tally = tallyRules(results);
  const failed = failedRules(results);
  const chips: { light: TrafficLight; label: string; count: number }[] = [
    { light: 'red', label: t('validation.light_error', { defaultValue: 'Errors' }), count: tally.red },
    { light: 'amber', label: t('validation.light_warning', { defaultValue: 'Warnings' }), count: tally.amber },
    { light: 'blue', label: t('validation.light_info', { defaultValue: 'Notes' }), count: tally.blue },
    { light: 'green', label: t('validation.light_passed', { defaultValue: 'Passed' }), count: tally.green },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {chips.map((c) => (
          <span
            key={c.light}
            className="inline-flex items-center gap-1.5 rounded-full border border-border-light px-2.5 py-1 text-xs text-content-secondary"
          >
            <LightDot light={c.light} />
            {c.label}
            <span className="font-semibold tabular-nums text-content-primary">{c.count}</span>
          </span>
        ))}
      </div>
      {results.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('validation.no_results', { defaultValue: 'Nothing to check yet. Rules run as soon as there is data.' })}
        </p>
      ) : failed.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-content-secondary">
          <LightDot light="green" />
          {t('validation.all_passed', { defaultValue: 'All checks passed.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light rounded-lg border border-border-light">
          {failed.map((r, i) => {
            const { key, params } = ruleMessage(r);
            const text = key ? t(key, { ...params, defaultValue: r.message }) : r.message;
            return (
              <li key={`${r.rule_id}-${r.element_ref ?? ''}-${i}`} className="flex items-start gap-2.5 px-3 py-2 text-sm">
                <LightDot light={ruleLight(r)} className="mt-1.5" />
                <span className="text-content-primary">{text}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
