// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ChatMessage, ChatSession } from '../../types';
import MessageThread from './MessageThread';
import InputBar from './InputBar';
import ChatHistory from './ChatHistory';

interface ChatLeftPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  suggestions: string[];
  onSend: (text: string) => void;
  onClear: () => void;
  aiConfigured: boolean | null;
  sessions: ChatSession[];
  sessionsTotal: number;
  sessionsLoading: boolean;
  loadingSessionId: string | null;
  activeSessionId: string | null;
  onLoadSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}

export default function ChatLeftPanel({
  messages,
  isStreaming,
  suggestions,
  onSend,
  onClear,
  aiConfigured,
  sessions,
  sessionsTotal,
  sessionsLoading,
  loadingSessionId,
  activeSessionId,
  onLoadSession,
  onDeleteSession,
}: ChatLeftPanelProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--chat-bg)',
        fontFamily: 'var(--chat-font-body)',
      }}
    >
      <ChatHistory
        sessions={sessions}
        sessionsTotal={sessionsTotal}
        sessionsLoading={sessionsLoading}
        loadingSessionId={loadingSessionId}
        activeSessionId={activeSessionId}
        onLoad={onLoadSession}
        onDelete={onDeleteSession}
        onNew={onClear}
      />
      <MessageThread messages={messages} isStreaming={isStreaming} aiConfigured={aiConfigured} />
      <InputBar
        onSend={onSend}
        onClear={onClear}
        hasMessages={messages.length > 0}
        isStreaming={isStreaming}
        suggestions={suggestions}
      />
    </div>
  );
}
