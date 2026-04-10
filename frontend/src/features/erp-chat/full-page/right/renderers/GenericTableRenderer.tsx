export default function GenericTableRenderer({ data }: { data: unknown }) {
  const rows: Record<string, unknown>[] = Array.isArray(data) ? data : [];

  if (rows.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No data to display
      </div>
    );
  }

  // Auto-generate columns from keys of the first item
  const columns = Object.keys(rows[0] ?? {});

  if (columns.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        Empty data
      </div>
    );
  }

  const cellBase: React.CSSProperties = {
    padding: '7px 10px',
    borderBottom: '1px solid var(--chat-border-subtle)',
    fontSize: 12,
    fontFamily: 'var(--chat-font-body)',
    verticalAlign: 'top',
    maxWidth: 240,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  };

  function formatValue(val: unknown): string {
    if (val == null) return '-';
    if (typeof val === 'number') return val.toLocaleString();
    if (typeof val === 'boolean') return val ? 'Yes' : 'No';
    if (typeof val === 'object') return JSON.stringify(val);
    return String(val);
  }

  return (
    <div style={{ overflow: 'auto', height: '100%' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', color: 'var(--chat-text-primary)' }}>
        <thead>
          <tr style={{ background: 'var(--chat-surface-2)' }}>
            {columns.map((col) => (
              <th
                key={col}
                style={{
                  ...cellBase,
                  fontWeight: 600,
                  textAlign: 'left',
                  textTransform: 'capitalize',
                }}
              >
                {col.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} style={{ background: ri % 2 === 0 ? 'transparent' : 'var(--chat-surface-1)' }}>
              {columns.map((col) => (
                <td
                  key={col}
                  style={{
                    ...cellBase,
                    fontFamily: typeof row[col] === 'number' ? 'var(--chat-font-mono)' : 'var(--chat-font-body)',
                    textAlign: typeof row[col] === 'number' ? 'right' : 'left',
                  }}
                  title={String(row[col] ?? '')}
                >
                  {formatValue(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
