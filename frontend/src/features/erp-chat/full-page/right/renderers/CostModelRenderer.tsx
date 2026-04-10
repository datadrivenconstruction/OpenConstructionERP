interface CostModelData {
  bac?: number;
  eac?: number;
  spi?: number;
  cpi?: number;
  planned?: number[];
  actual?: number[];
  earned?: number[];
  periods?: string[];
}

function formatNumber(n: number | undefined): string {
  if (n == null) return '-';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(2);
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
    { data: planned, color: 'var(--chat-text-tertiary)', label: 'Planned' },
    { data: actual, color: 'var(--chat-tool-running)', label: 'Actual' },
    { data: earned, color: 'var(--chat-tool-done)', label: 'Earned' },
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

export default function CostModelRenderer({ data }: { data: unknown }) {
  const model = (data && typeof data === 'object' ? data : {}) as CostModelData;

  const hasKPIs = model.bac != null || model.eac != null || model.spi != null || model.cpi != null;
  const hasChart = model.planned?.length || model.actual?.length || model.earned?.length;

  if (!hasKPIs && !hasChart) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No cost model data available
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
