interface ToolBadgeProps {
  toolName: string;
  summary: string;
  durationMs?: number;
  onRefresh?: () => void;
}

export default function ToolBadge({ toolName, summary, durationMs, onRefresh }: ToolBadgeProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border-subtle)',
        fontFamily: 'var(--chat-font-mono)',
        fontSize: 12,
        minHeight: 36,
      }}
    >
      <span style={{ color: 'var(--chat-text-tertiary)' }}>&#9881;</span>
      <span style={{ color: 'var(--chat-accent)', fontWeight: 500 }}>{toolName}</span>
      {summary && (
        <span
          style={{
            color: 'var(--chat-text-secondary)',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {summary}
        </span>
      )}
      {durationMs !== undefined && (
        <span style={{ color: 'var(--chat-text-tertiary)', flexShrink: 0 }}>
          {durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s`}
        </span>
      )}
      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          style={{
            background: 'var(--chat-surface-2)',
            border: '1px solid var(--chat-border-subtle)',
            borderRadius: 'var(--chat-radius-sm)',
            color: 'var(--chat-text-secondary)',
            padding: '3px 8px',
            fontSize: 11,
            fontFamily: 'var(--chat-font-mono)',
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          Refresh
        </button>
      )}
    </div>
  );
}
