import { useRef, useEffect } from 'react';
import type { ChatMessage } from '../../types';
import MessageBubble from './MessageBubble';

interface MessageThreadProps {
  messages: ChatMessage[];
  isStreaming: boolean;
}

export default function MessageThread({ messages, isStreaming }: MessageThreadProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom during streaming or new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages, isStreaming]);

  if (messages.length === 0) {
    return (
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          color: 'var(--chat-text-tertiary)',
          fontFamily: 'var(--chat-font-body)',
          fontSize: 14,
          gap: 8,
          textAlign: 'center',
        }}
      >
        <span style={{ fontSize: 32, opacity: 0.4 }}>&#9672;</span>
        <span>Start a conversation with the ERP AI Assistant</span>
        <span style={{ fontSize: 12 }}>Ask about projects, BOQs, costs, or validation</span>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 16px 8px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      {messages.map((msg, idx) => {
        const isLast = idx === messages.length - 1;
        const showCursor = isLast && msg.role === 'assistant' && isStreaming;
        return <MessageBubble key={msg.id} message={msg} isStreaming={showCursor} />;
      })}
      <div ref={bottomRef} />
    </div>
  );
}
