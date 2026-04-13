interface CWICRItem {
  code?: string;
  description?: string;
  unit?: string;
  rate?: number;
  currency?: string;
  region?: string;
  category?: string;
}

export default function CWICRRenderer({ data }: { data: unknown }) {
  const items: CWICRItem[] = Array.isArray(data) ? data : [];

  if (items.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No CWICR results found
      </div>
    );
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((item, i) => (
        <div
          key={item.code ?? i}
          style={{
            background: 'var(--chat-surface-1)',
            border: '1px solid var(--chat-border-subtle)',
            borderRadius: 'var(--chat-radius)',
            padding: '10px 12px',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
            <div style={{ flex: 1 }}>
              {item.code && (
                <span
                  style={{
                    fontFamily: 'var(--chat-font-mono)',
                    fontSize: 12,
                    color: 'var(--chat-accent)',
                    fontWeight: 500,
                    marginRight: 8,
                  }}
                >
                  {item.code}
                </span>
              )}
              <span style={{ fontSize: 13, color: 'var(--chat-text-primary)', fontFamily: 'var(--chat-font-body)' }}>
                {item.description ?? '-'}
              </span>
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 700,
                fontFamily: 'var(--chat-font-mono)',
                color: 'var(--chat-text-primary)',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {item.rate != null
                ? item.rate.toLocaleString(undefined, { minimumFractionDigits: 2 })
                : '-'}
              {item.currency && (
                <span style={{ fontSize: 11, color: 'var(--chat-text-tertiary)', marginLeft: 3 }}>
                  {item.currency}
                </span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: 11, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)' }}>
            {item.unit && <span>Unit: {item.unit}</span>}
            {item.region && <span>Region: {item.region}</span>}
            {item.category && <span>Category: {item.category}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
