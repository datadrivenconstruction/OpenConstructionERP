// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { unwrapList, toNum } from './normalize';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface CompareData {
  metrics?: { label: string; values: (string | number | null)[] }[];
  columns?: string[];
}

interface CompareProject {
  id?: string;
  name?: string;
  code?: string;
  status?: string;
  contract_value?: number;
  budget_estimate?: number;
  region?: string;
  currency?: string;
}

function isNumeric(v: unknown): v is number {
  return typeof v === 'number' && !isNaN(v);
}

/**
 * The backend `compare_projects` tool returns a flat list of project rows
 * (`{ projects: [...] }`). Pivot it into the metric-by-project matrix the
 * table renderer expects: one column per project, one row per metric.
 */
function projectsToMatrix(projects: CompareProject[]): CompareData {
  if (projects.length === 0) return { metrics: [], columns: [] };
  const columns = projects.map((p) => p.name ?? p.code ?? 'Project');
  const metricKeys: { label: string; get: (p: CompareProject) => string | number | null }[] = [
    { label: 'Status', get: (p) => p.status ?? null },
    { label: 'Region', get: (p) => p.region ?? null },
    { label: 'Currency', get: (p) => p.currency ?? null },
    { label: 'Contract value', get: (p) => toNum(p.contract_value) ?? null },
    { label: 'Budget estimate', get: (p) => toNum(p.budget_estimate) ?? null },
  ];
  const metrics = metricKeys
    .map((m) => ({ label: m.label, values: projects.map(m.get) }))
    // Drop metric rows where every project is null/empty so the table stays tight.
    .filter((row) => row.values.some((v) => v != null && v !== ''));
  return { metrics, columns };
}

export default function CompareRenderer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const d = (data && typeof data === 'object' ? data : {}) as CompareData;
  // Prefer the pre-built matrix if a caller supplied it; otherwise pivot the
  // backend's `{ projects: [...] }` list.
  const pivoted = d.metrics ? d : projectsToMatrix(unwrapList(data, ['projects']) as CompareProject[]);
  const metrics = pivoted.metrics ?? [];
  const columns = pivoted.columns ?? [];

  if (metrics.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        {t('erp_chat.compare.no_data', { defaultValue: 'No comparison data available' })}
      </div>
    );
  }

  const cellBase: React.CSSProperties = {
    padding: '8px 10px',
    borderBottom: '1px solid var(--chat-border-subtle)',
    fontSize: 13,
    fontFamily: 'var(--chat-font-body)',
    verticalAlign: 'middle',
  };

  return (
    <div style={{ overflow: 'auto', height: '100%' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', color: 'var(--chat-text-primary)' }}>
        <thead>
          <tr style={{ background: 'var(--chat-surface-2)' }}>
            <th style={{ ...cellBase, fontWeight: 600, textAlign: 'left', minWidth: 120 }}>{t('erp_chat.compare.metric', { defaultValue: 'Metric' })}</th>
            {columns.map((col) => (
              <th key={col} style={{ ...cellBase, fontWeight: 600, textAlign: 'right', minWidth: 100 }}>
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((row, ri) => {
            // Find best/worst for numeric rows
            const numericValues = row.values.filter(isNumeric);
            const hasBest = numericValues.length > 1;
            const best = hasBest ? Math.min(...numericValues) : null;
            const worst = hasBest ? Math.max(...numericValues) : null;

            return (
              <tr key={ri} style={{ background: ri % 2 === 0 ? 'transparent' : 'var(--chat-surface-1)' }}>
                <td style={{ ...cellBase, fontWeight: 500 }}>{row.label}</td>
                {row.values.map((val, vi) => {
                  let color = 'var(--chat-text-primary)';
                  if (hasBest && isNumeric(val)) {
                    if (val === best) color = 'var(--chat-tool-done)';
                    else if (val === worst) color = 'var(--chat-tool-error)';
                  }
                  const display = isNumeric(val)
                    ? val.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 })
                    : val ?? '-';
                  return (
                    <td
                      key={vi}
                      style={{
                        ...cellBase,
                        textAlign: 'right',
                        fontFamily: isNumeric(val) ? 'var(--chat-font-mono)' : 'var(--chat-font-body)',
                        color,
                        fontWeight: hasBest && isNumeric(val) && (val === best || val === worst) ? 600 : 400,
                      }}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
