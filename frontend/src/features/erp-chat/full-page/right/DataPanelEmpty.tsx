interface DataPanelEmptyProps {
  onSuggestion?: (text: string) => void;
}

const SUGGESTIONS = [
  'Show all projects',
  'BOQ analysis',
  'Validation status',
  'Risk overview',
];

export default function DataPanelEmpty({ onSuggestion }: DataPanelEmptyProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: 32,
        fontFamily: 'var(--chat-font-body)',
        textAlign: 'center',
        gap: 12,
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: 'var(--chat-surface-2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 24,
          color: 'var(--chat-text-tertiary)',
        }}
      >
        &#9638;
      </div>
      <div style={{ color: 'var(--chat-text-secondary)', fontSize: 14, maxWidth: 280 }}>
        Data will appear here as you chat with the AI
      </div>
      <div style={{ color: 'var(--chat-text-tertiary)', fontSize: 12, marginTop: 4 }}>
        Try one of these to get started:
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginTop: 4 }}>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSuggestion?.(s)}
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontFamily: 'var(--chat-font-body)',
              color: 'var(--chat-text-secondary)',
              background: 'var(--chat-surface-2)',
              border: '1px solid var(--chat-border-subtle)',
              borderRadius: 16,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-accent)';
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-primary)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-border-subtle)';
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-secondary)';
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
