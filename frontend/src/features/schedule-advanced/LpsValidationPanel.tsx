// Last Planner validation​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Findings of the last_planner rule set over one master schedule. */
import { useTranslation } from 'react-i18next';
import { Badge, Card } from '@/shared/ui';
import { useLpsValidation } from './api';

export function LpsValidationPanel({ masterId }: { masterId: string }) {
  const { t, i18n } = useTranslation();
  const q = useLpsValidation(masterId, (i18n.language || 'en').split('-')[0]);
  if (q.isLoading || q.isError || !q.data) return null;
  const findings = q.data.results.filter((r) => !r.passed);
  return (
    <Card padding="md">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('schedule_advanced.lps_validation_title', { defaultValue: 'Last Planner checks' })}
        </h3>
        <Badge variant={q.data.errors > 0 ? 'error' : 'success'} size="sm">
          {t('schedule_advanced.lps_errors', { defaultValue: '{{count}} errors', count: q.data.errors })}
        </Badge>
        <Badge variant={q.data.warnings > 0 ? 'warning' : 'neutral'} size="sm">
          {t('schedule_advanced.lps_warnings', { defaultValue: '{{count}} warnings', count: q.data.warnings })}
        </Badge>
      </div>
      {findings.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('schedule_advanced.lps_all_pass', { defaultValue: 'All Last Planner checks pass.' })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {findings.map((r, i) => (
            <li key={`${r.rule_id}-${r.element_ref ?? i}`} className="flex items-start gap-2 text-xs" data-testid="lps-finding">
              <Badge variant={r.severity === 'error' ? 'error' : 'warning'} size="sm">
                {r.severity === 'error'
                  ? t('schedule_advanced.lps_sev_error', { defaultValue: 'Error' })
                  : t('schedule_advanced.lps_sev_warning', { defaultValue: 'Warning' })}
              </Badge>
              <span className="text-content-primary">
                {r.message}
                {r.suggestion ? <span className="text-content-tertiary"> {r.suggestion}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
