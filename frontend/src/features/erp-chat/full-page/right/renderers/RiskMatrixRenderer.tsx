interface RiskItem {
  probability?: number;
  impact?: number;
  name?: string;
  id?: string;
}

function riskZone(prob: number, impact: number): string {
  const score = prob * impact;
  if (score >= 16) return 'var(--chat-tool-error)';
  if (score >= 9) return 'var(--chat-accent)';
  if (score >= 4) return '#c09c3e';
  return 'var(--chat-tool-done)';
}

export default function RiskMatrixRenderer({ data }: { data: unknown }) {
  const risks: RiskItem[] = Array.isArray(data) ? data : [];

  if (risks.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No risk data available
      </div>
    );
  }

  // Build 5x5 grid (impact rows from 5 to 1, probability columns from 1 to 5)
  const grid: Record<string, RiskItem[]> = {};
  for (const r of risks) {
    const p = Math.min(5, Math.max(1, Math.round(r.probability ?? 1)));
    const imp = Math.min(5, Math.max(1, Math.round(r.impact ?? 1)));
    const key = `${imp}-${p}`;
    if (!grid[key]) grid[key] = [];
    grid[key].push(r);
  }

  const cellSize = 52;

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 16, fontFamily: 'var(--chat-font-body)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4 }}>
        {/* Y-axis label */}
        <div
          style={{
            writingMode: 'vertical-lr',
            transform: 'rotate(180deg)',
            fontSize: 11,
            fontFamily: 'var(--chat-font-mono)',
            color: 'var(--chat-text-tertiary)',
            textAlign: 'center',
            paddingBottom: 20,
          }}
        >
          IMPACT
        </div>
        <div>
          {/* Grid rows: impact 5 (top) to 1 (bottom) */}
          {[5, 4, 3, 2, 1].map((impact) => (
            <div key={impact} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <div
                style={{
                  width: 18,
                  fontSize: 10,
                  fontFamily: 'var(--chat-font-mono)',
                  color: 'var(--chat-text-tertiary)',
                  textAlign: 'right',
                }}
              >
                {impact}
              </div>
              {[1, 2, 3, 4, 5].map((prob) => {
                const key = `${impact}-${prob}`;
                const items = grid[key] ?? [];
                const bgColor = riskZone(prob, impact);
                return (
                  <div
                    key={prob}
                    title={items.map((r) => r.name ?? r.id).join(', ') || `P${prob} I${impact}`}
                    style={{
                      width: cellSize,
                      height: cellSize,
                      background: bgColor,
                      opacity: items.length > 0 ? 0.85 : 0.15,
                      borderRadius: 'var(--chat-radius-sm)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: 1,
                      cursor: items.length > 0 ? 'default' : undefined,
                      transition: 'opacity 0.15s',
                    }}
                  >
                    {items.length > 0 && (
                      <span
                        style={{
                          fontSize: 14,
                          fontWeight: 700,
                          fontFamily: 'var(--chat-font-mono)',
                          color: '#0d1117',
                        }}
                      >
                        {items.length}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
          {/* X-axis labels */}
          <div style={{ display: 'flex', marginLeft: 20, marginTop: 4 }}>
            {[1, 2, 3, 4, 5].map((p) => (
              <div
                key={p}
                style={{
                  width: cellSize + 2,
                  textAlign: 'center',
                  fontSize: 10,
                  fontFamily: 'var(--chat-font-mono)',
                  color: 'var(--chat-text-tertiary)',
                }}
              >
                {p}
              </div>
            ))}
          </div>
          <div
            style={{
              textAlign: 'center',
              marginLeft: 20,
              fontSize: 11,
              fontFamily: 'var(--chat-font-mono)',
              color: 'var(--chat-text-tertiary)',
              marginTop: 2,
            }}
          >
            PROBABILITY
          </div>
        </div>
      </div>

      {/* Summary */}
      <div
        style={{
          marginTop: 16,
          paddingTop: 10,
          borderTop: '1px solid var(--chat-border-subtle)',
          fontSize: 12,
          color: 'var(--chat-text-secondary)',
          fontFamily: 'var(--chat-font-mono)',
        }}
      >
        {risks.length} total risks
      </div>
    </div>
  );
}
