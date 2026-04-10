import { useState, useRef, useCallback, type KeyboardEvent, type ChangeEvent } from 'react';

interface InputBarProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  suggestions: string[];
}

export default function InputBar({ onSend, isStreaming, suggestions }: InputBarProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-grow
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, isStreaming, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleSuggestion = useCallback(
    (text: string) => {
      if (isStreaming) return;
      onSend(text);
    },
    [isStreaming, onSend],
  );

  const canSend = value.trim().length > 0 && !isStreaming;

  return (
    <div
      style={{
        borderTop: '1px solid var(--chat-border-subtle)',
        padding: '10px 16px 12px',
        background: 'var(--chat-surface-1)',
      }}
    >
      {/* Suggestion chips */}
      {suggestions.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            marginBottom: 10,
          }}
        >
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => handleSuggestion(s)}
              disabled={isStreaming}
              style={{
                padding: '5px 12px',
                fontSize: 12,
                fontFamily: 'var(--chat-font-body)',
                color: isStreaming ? 'var(--chat-text-tertiary)' : 'var(--chat-text-secondary)',
                background: 'var(--chat-surface-2)',
                border: '1px solid var(--chat-border-subtle)',
                borderRadius: 16,
                cursor: isStreaming ? 'not-allowed' : 'pointer',
                transition: 'background 0.15s, border-color 0.15s',
                whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => {
                if (!isStreaming) {
                  (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-accent)';
                  (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-primary)';
                }
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
      )}

      {/* Input area */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'flex-end',
        }}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={isStreaming ? 'AI is responding...' : 'Ask anything about your ERP data...'}
          rows={1}
          style={{
            flex: 1,
            resize: 'none',
            padding: '10px 12px',
            fontSize: 14,
            fontFamily: 'var(--chat-font-body)',
            color: 'var(--chat-text-primary)',
            background: 'var(--chat-surface-2)',
            border: '1px solid var(--chat-border)',
            borderRadius: 'var(--chat-radius)',
            outline: 'none',
            lineHeight: 1.5,
            maxHeight: 200,
            overflow: 'auto',
            transition: 'border-color 0.15s',
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = 'var(--chat-accent)';
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = 'var(--chat-border)';
          }}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!canSend}
          aria-label="Send message"
          style={{
            width: 40,
            height: 40,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: canSend ? 'var(--chat-accent)' : 'var(--chat-surface-3)',
            color: canSend ? '#0d1117' : 'var(--chat-text-tertiary)',
            border: 'none',
            borderRadius: 'var(--chat-radius)',
            cursor: canSend ? 'pointer' : 'not-allowed',
            fontSize: 18,
            flexShrink: 0,
            transition: 'background 0.15s, color 0.15s',
          }}
        >
          &#9654;
        </button>
      </div>

      {/* Keyboard hint */}
      <div
        style={{
          marginTop: 6,
          fontSize: 11,
          fontFamily: 'var(--chat-font-mono)',
          color: 'var(--chat-text-tertiary)',
          textAlign: 'center',
        }}
      >
        Enter to send &middot; Shift+Enter for newline
      </div>
    </div>
  );
}
