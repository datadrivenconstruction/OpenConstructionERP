import { useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import type { ChatMessage } from '../../types';
import MessageBubble from './MessageBubble';

interface MessageThreadProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  aiConfigured: boolean | null;
}

export default function MessageThread({ messages, isStreaming, aiConfigured }: MessageThreadProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom during streaming or new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages, isStreaming]);

  if (messages.length === 0) {
    // Show onboarding card when AI is not configured
    if (aiConfigured === false) {
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
            fontFamily: 'var(--chat-font-body)',
            gap: 8,
          }}
        >
          <div
            style={{
              maxWidth: 380,
              padding: '24px 28px',
              borderRadius: 16,
              background: 'var(--chat-surface-1)',
              border: '1px solid var(--chat-border)',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                background: 'var(--chat-accent)',
                color: '#ffffff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
                fontSize: 22,
              }}
            >
              &#9881;
            </div>
            <div
              style={{
                fontWeight: 700,
                fontSize: 15,
                color: 'var(--chat-text-primary)',
                marginBottom: 8,
              }}
            >
              {t('chat.onboarding_title', { defaultValue: 'AI assistant is not configured yet' })}
            </div>
            <div
              style={{
                fontSize: 13,
                color: 'var(--chat-text-secondary)',
                lineHeight: 1.55,
                marginBottom: 16,
              }}
            >
              {t('chat.onboarding_desc', {
                defaultValue:
                  'Connect your AI provider (Anthropic, OpenAI, or Google) in Settings to enable the chat assistant.',
              })}
            </div>
            <Link
              to="/settings"
              style={{
                display: 'inline-block',
                padding: '10px 20px',
                borderRadius: 'var(--chat-radius)',
                background: 'var(--chat-accent)',
                color: '#ffffff',
                textDecoration: 'none',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              {t('chat.go_to_settings', { defaultValue: 'Go to Settings' })}
            </Link>
          </div>
        </div>
      );
    }

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
        <span>{t('chat.empty_title', { defaultValue: 'Start a conversation with the ERP AI Assistant' })}</span>
        <span style={{ fontSize: 12 }}>{t('chat.empty_subtitle', { defaultValue: 'Ask about projects, BOQs, costs, or validation' })}</span>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 4px 8px',
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
