interface CompareData {
  metrics?: { label: string; values: (string | number | null)[] }[];
  columns?: string[];
}

function isNumeric(v: unknown): v is number {
  return typeof v === 'number' && !isNaN(v);
}

export default function CompareRenderer({ data }: { data: unknown }) {
  const d = (data && typeof data === 'object' ? data : {}) as CompareData;
  const metrics = d.metrics ?? [];
  const columns = d.columns ?? [];

  if (metrics.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No comparison data available
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
            <th style={{ ...cellBase, fontWeight: 600, textAlign: 'left', minWidth: 120 }}>Metric</th>
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
                    ? val.toLocaleString(undefined, { maximumFractionDigits: 2 })
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
