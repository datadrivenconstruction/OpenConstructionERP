/**
 * Failed commercial control rules (budget basis, unmapped cost, over-commitment,
 * approval bands, valuation stages). The server translates each message, so
 * this only lays them out: errors first, then warnings.
 */
import { useTranslation } from 'react-i18next';
import { AlertTriangle, XCircle } from 'lucide-react';
import type { CommercialFinding } from './api';

interface Props {
  findings: CommercialFinding[];
  /** Show at most this many; the rest are counted. */
  limit?: number;
  compact?: boolean;
}

export function CommercialFindings({ findings, limit = 8, compact = false }: Props) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  const sorted = [...findings].sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error'));
  const shown = sorted.slice(0, limit);
  const hidden = sorted.length - shown.length;
  return (
    <ul className={compact ? 'space-y-0.5 text-2xs' : 'space-y-1 text-xs'} data-testid="commercial-findings">
      {shown.map((f, i) => {
        const isError = f.severity === 'error';
        const Icon = isError ? XCircle : AlertTriangle;
        return (
          <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} className="flex items-start gap-1.5">
            <Icon
              size={compact ? 12 : 14}
              className={'mt-0.5 shrink-0 ' + (isError ? 'text-semantic-error' : 'text-semantic-warning')}
            />
            <span>
              <span className="text-content-primary">{f.message}</span>
              {!compact && f.suggestion && <span className="text-content-tertiary"> {f.suggestion}</span>}
            </span>
          </li>
        );
      })}
      {hidden > 0 && (
        <li className="text-content-tertiary">
          {t('commercial_control.more_findings', { defaultValue: '{{count}} more', count: hidden })}
        </li>
      )}
    </ul>
  );
}
