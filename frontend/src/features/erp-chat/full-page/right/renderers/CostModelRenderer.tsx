// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { toNum } from './normalize';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface CostModelData {
  bac?: number;
  eac?: number;
  spi?: number;
  cpi?: number;
  planned?: number[];
  actual?: number[];
  earned?: number[];
  periods?: string[];
  // Backend `get_cost_model` cost-breakdown shape.
  boq_name?: string;
  direct_cost?: number;
  net_total?: number;
  grand_total?: number;
  sections?: { title?: string; subtotal?: number; position_count?: number }[];
  markups?: { name?: string; category?: string; percentage?: number; amount?: number }[];
}

function formatNumber(n: number | undefined): string {
  if (n == null) return '-';
  if (Math.abs(n) >= 1_000_000) return `${fmtFixed(n / 1_000_000, 1)}M`;
  if (Math.abs(n) >= 1_000) return `${fmtFixed(n / 1_000, 0)}K`;
  return fmtFixed(n, 2);
}

function kpiColor(label: string, value: number | undefined): string {
  if (value == null) return 'var(--chat-text-secondary)';
  if (label === 'SPI' || label === 'CPI') {
    if (value >= 1) return 'var(--chat-tool-done)';
    if (value >= 0.9) return 'var(--chat-accent)';
    return 'var(--chat-tool-error)';
  }
  return 'var(--chat-text-primary)';
}

function KPICard({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div
      style={{
        background: 'var(--chat-surface-1)',
        border: '1px solid var(--chat-border-subtle)',
        borderRadius: 'var(--chat-radius)',
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      <div style={{ fontSize: 11, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          fontFamily: 'var(--chat-font-mono)',
          color: kpiColor(label, value),
        }}
      >
        {formatNumber(value)}
      </div>
    </div>
  );
}

function MiniChart({ planned, actual, earned }: { planned?: number[]; actual?: number[]; earned?: number[] }) {
  const { t } = useTranslation();
  const allSeries = [planned, actual, earned].filter(Boolean) as number[][];
  if (allSeries.length === 0) return null;

  const maxLen = Math.max(...allSeries.map((s) => s.length));
  const maxVal = Math.max(...allSeries.flat(), 1);

  const W = 400;
  const H = 150;
  const padX = 0;
  const padY = 10;

  function toPoints(series: number[]): string {
    return series
      .map((v, i) => {
        const x = padX + (i / (maxLen - 1 || 1)) * (W - 2 * padX);
        const y = padY + (1 - v / maxVal) * (H - 2 * padY);
        return `${x},${y}`;
      })
      .join(' ');
  }

  const seriesConfig: { data: number[] | undefined; color: string; label: string }[] = [
    { data: planned, color: 'var(--chat-text-tertiary)', label: t('erp_chat.cost_model.planned', { defaultValue: 'Planned' }) },
    { data: actual, color: 'var(--chat-tool-running)', label: t('erp_chat.cost_model.actual', { defaultValue: 'Actual' }) },
    { data: earned, color: 'var(--chat-tool-done)', label: t('erp_chat.cost_model.earned', { defaultValue: 'Earned' }) },
  ];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', maxHeight: 180 }}>
        {seriesConfig.map(
          ({ data: s, color }) =>
            s &&
            s.length > 1 && (
              <polyline
                key={color}
                fill="none"
                stroke={color}
                strokeWidth={2}
                points={toPoints(s)}
              />
            ),
        )}
      </svg>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 6 }}>
        {seriesConfig.map(
          ({ data: s, color, label }) =>
            s && (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontFamily: 'var(--chat-font-mono)' }}>
                <span style={{ width: 12, height: 2, background: color, display: 'inline-block', borderRadius: 1 }} />
                <span style={{ color: 'var(--chat-text-secondary)' }}>{label}</span>
              </div>
            ),
        )}
      </div>
    </div>
  );
}

function fmtMoney(n: number | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 });
}

/**
 * Cost-breakdown view matching the backend `get_cost_model` output:
 * direct cost, markups (with %/amount), section subtotals, and grand total.
 */
function CostBreakdown({ model }: { model: CostModelData }) {
  const { t } = useTranslation();
  const direct = toNum(model.direct_cost) ?? 0;
  const grand = toNum(model.grand_total) ?? 0;
  const markups = model.markups ?? [];
  const sections = model.sections ?? [];

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '8px 12px',
    fontSize: 13,
    borderBottom: '1px solid var(--chat-border-subtle)',
    fontFamily: 'var(--chat-font-body)',
  };
  const num: React.CSSProperties = { fontFamily: 'var(--chat-font-mono)', fontVariantNumeric: 'tabular-nums' };

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12, fontFamily: 'var(--chat-font-body)' }}>
      {model.boq_name && (
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--chat-text-primary)', marginBottom: 8 }}>
          {model.boq_name}
        </div>
      )}

      {/* KPI strip: direct cost + grand total */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, marginBottom: 16 }}>
        <KPICard label={t('erp_chat.cost_model.direct_cost', { defaultValue: 'Direct cost' })} value={direct} />
        <KPICard label={t('erp_chat.cost_model.grand_total', { defaultValue: 'Grand total' })} value={grand} />
      </div>

      {markups.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>
            {t('erp_chat.cost_model.markups', { defaultValue: 'Markups' })}
          </div>
          <div style={{ background: 'var(--chat-surface-1)', border: '1px solid var(--chat-border-subtle)', borderRadius: 'var(--chat-radius)' }}>
            {markups.map((m, i) => (
              <div key={m.name ?? i} style={rowStyle}>
                <span style={{ color: 'var(--chat-text-secondary)' }}>
                  {m.name ?? m.category ?? t('erp_chat.cost_model.markup_n', { defaultValue: 'Markup {{n}}', n: i + 1 })}
                  {m.percentage != null && (
                    <span style={{ color: 'var(--chat-text-tertiary)', marginLeft: 6 }}>{m.percentage}%</span>
                  )}
                </span>
                <span style={num}>{fmtMoney(toNum(m.amount))}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sections.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>
            {t('erp_chat.cost_model.sections', { defaultValue: 'Sections' })}
          </div>
          <div style={{ background: 'var(--chat-surface-1)', border: '1px solid var(--chat-border-subtle)', borderRadius: 'var(--chat-radius)' }}>
            {sections.map((s, i) => (
              <div key={s.title ?? i} style={rowStyle}>
                <span style={{ color: 'var(--chat-text-secondary)' }}>
                  {s.title ?? t('erp_chat.cost_model.section_n', { defaultValue: 'Section {{n}}', n: i + 1 })}
                  {s.position_count != null && (
                    <span style={{ color: 'var(--chat-text-tertiary)', marginLeft: 6 }}>
                      {t('erp_chat.cost_model.position_count', { defaultValue: '{{count}} pos', count: s.position_count })}
                    </span>
                  )}
                </span>
                <span style={num}>{fmtMoney(toNum(s.subtotal))}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function CostModelRenderer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const model = (data && typeof data === 'object' ? data : {}) as CostModelData;

  const hasKPIs = model.bac != null || model.eac != null || model.spi != null || model.cpi != null;
  const hasChart = model.planned?.length || model.actual?.length || model.earned?.length;
  // Backend cost-breakdown shape (the common case for the AI chat tool).
  const hasBreakdown =
    model.direct_cost != null ||
    model.grand_total != null ||
    (model.sections?.length ?? 0) > 0 ||
    (model.markups?.length ?? 0) > 0;

  if (!hasKPIs && !hasChart) {
    if (hasBreakdown) return <CostBreakdown model={model} />;
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        {t('erp_chat.cost_model.no_data', { defaultValue: 'No cost model data available' })}
      </div>
    );
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12, fontFamily: 'var(--chat-font-body)' }}>
      {hasKPIs && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
            gap: 8,
            marginBottom: 16,
          }}
        >
          <KPICard label="BAC" value={model.bac} />
          <KPICard label="EAC" value={model.eac} />
          <KPICard label="SPI" value={model.spi} />
          <KPICard label="CPI" value={model.cpi} />
        </div>
      )}
      {hasChart && (
        <div
          style={{
            background: 'var(--chat-surface-1)',
            border: '1px solid var(--chat-border-subtle)',
            borderRadius: 'var(--chat-radius)',
            padding: 12,
          }}
        >
          <MiniChart planned={model.planned} actual={model.actual} earned={model.earned} />
        </div>
      )}
    </div>
  );
}
