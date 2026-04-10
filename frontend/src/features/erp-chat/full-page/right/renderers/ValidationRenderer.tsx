import { useState } from 'react';

interface ValidationItem {
  rule_id?: string;
  rule_name?: string;
  severity?: 'error' | 'warning' | 'info' | 'critical';
  message?: string;
  element_ref?: string;
  details?: Record<string, unknown>;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'var(--chat-tool-error)',
  error: 'var(--chat-tool-error)',
  warning: '#f0883e',
  info: 'var(--chat-tool-running)',
};

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  error: 1,
  warning: 2,
  info: 3,
};

function groupBySeverity(items: ValidationItem[]): Record<string, ValidationItem[]> {
  const groups: Record<string, ValidationItem[]> = {};
  for (const item of items) {
    const sev = item.severity ?? 'info';
    if (!groups[sev]) groups[sev] = [];
    groups[sev].push(item);
  }
  return groups;
}

function ValidationItemRow({ item }: { item: ValidationItem }) {
  const [expanded, setExpanded] = useState(false);
  const color = SEVERITY_COLORS[item.severity ?? 'info'] ?? 'var(--chat-text-secondary)';

  return (
    <div
      style={{
        background: 'var(--chat-surface-1)',
        border: '1px solid var(--chat-border-subtle)',
        borderLeft: `3px solid ${color}`,
        borderRadius: 'var(--chat-radius-sm)',
        marginBottom: 4,
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
          width: '100%',
          padding: '8px 10px',
          background: 'none',
          border: 'none',
          color: 'var(--chat-text-primary)',
          cursor: 'pointer',
          textAlign: 'left',
          fontFamily: 'var(--chat-font-body)',
          fontSize: 13,
        }}
      >
        <span style={{ flex: 1 }}>
          <span style={{ fontWeight: 500 }}>{item.rule_name ?? item.rule_id ?? 'Rule'}</span>
          {item.message && (
            <span style={{ color: 'var(--chat-text-secondary)', display: 'block', fontSize: 12, marginTop: 2 }}>
              {item.message}
            </span>
          )}
        </span>
        {item.element_ref && (
          <span
            style={{
              fontSize: 11,
              fontFamily: 'var(--chat-font-mono)',
              color: 'var(--chat-text-tertiary)',
              flexShrink: 0,
            }}
          >
            {item.element_ref}
          </span>
        )}
      </button>
      {expanded && item.details && (
        <div
          style={{
            borderTop: '1px solid var(--chat-border-subtle)',
            padding: '8px 10px',
            fontFamily: 'var(--chat-font-mono)',
            fontSize: 11,
            color: 'var(--chat-text-secondary)',
          }}
        >
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {JSON.stringify(item.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function ValidationRenderer({ data }: { data: unknown }) {
  const items: ValidationItem[] = Array.isArray(data) ? data : [];

  if (items.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No validation results
      </div>
    );
  }

  const groups = groupBySeverity(items);
  const sortedKeys = Object.keys(groups).sort(
    (a, b) => (SEVERITY_ORDER[a] ?? 99) - (SEVERITY_ORDER[b] ?? 99),
  );

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12 }}>
      {sortedKeys.map((severity) => {
        const groupItems = groups[severity]!;
        const color = SEVERITY_COLORS[severity] ?? 'var(--chat-text-secondary)';
        return (
          <div key={severity} style={{ marginBottom: 16 }}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                fontFamily: 'var(--chat-font-mono)',
                color,
                textTransform: 'uppercase',
                marginBottom: 8,
                letterSpacing: '0.05em',
              }}
            >
              {groupItems.length} {severity}{groupItems.length !== 1 ? 's' : ''}
            </div>
            {groupItems.map((item, i) => (
              <ValidationItemRow key={item.rule_id ?? i} item={item} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
