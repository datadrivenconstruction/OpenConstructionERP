import type { ChatMessage } from '../../types';
import ToolCallCard from './ToolCallCard';
import StreamingCursor from './StreamingCursor';

function formatTime(d: Date): string {
  const h = d.getHours().toString().padStart(2, '0');
  const m = d.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const { role, content, toolCalls, ts } = message;

  if (role === 'system') {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '6px 0',
          color: 'var(--chat-text-tertiary)',
          fontSize: 12,
          fontFamily: 'var(--chat-font-mono)',
          animation: 'msgIn 0.3s ease-out',
        }}
      >
        {content}
      </div>
    );
  }

  if (role === 'user') {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          padding: '4px 0',
          animation: 'msgIn 0.3s ease-out',
        }}
      >
        <div
          style={{
            background: 'var(--chat-surface-3)',
            color: 'var(--chat-text-primary)',
            padding: '10px 14px',
            borderRadius: '16px 16px 4px 16px',
            maxWidth: '85%',
            fontSize: 14,
            lineHeight: 1.55,
            fontFamily: 'var(--chat-font-body)',
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          {content}
        </div>
        <span
          style={{
            fontSize: 11,
            color: 'var(--chat-text-tertiary)',
            fontFamily: 'var(--chat-font-mono)',
            marginTop: 3,
            paddingRight: 2,
          }}
        >
          {formatTime(ts)}
        </span>
      </div>
    );
  }

  // assistant
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        padding: '4px 0',
        animation: 'msgIn 0.3s ease-out',
      }}
    >
      <div
        style={{
          borderLeft: '2px solid var(--chat-accent)',
          paddingLeft: 12,
          maxWidth: '92%',
        }}
      >
        {/* Tool call cards */}
        {toolCalls && toolCalls.length > 0 && (
          <div style={{ marginBottom: 6 }}>
            {toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} tool={tc} />
            ))}
          </div>
        )}

        {/* Text content */}
        {(content || isStreaming) && (
          <div
            style={{
              color: 'var(--chat-text-primary)',
              fontSize: 14,
              lineHeight: 1.6,
              fontFamily: 'var(--chat-font-body)',
              wordBreak: 'break-word',
              whiteSpace: 'pre-wrap',
            }}
          >
            {content}
            {isStreaming && <StreamingCursor />}
          </div>
        )}
      </div>
      <span
        style={{
          fontSize: 11,
          color: 'var(--chat-text-tertiary)',
          fontFamily: 'var(--chat-font-mono)',
          marginTop: 3,
          paddingLeft: 14,
        }}
      >
        {formatTime(ts)}
      </span>
    </div>
  );
}
