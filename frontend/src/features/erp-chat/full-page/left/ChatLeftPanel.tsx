import type { ChatMessage } from '../../types';
import MessageThread from './MessageThread';
import InputBar from './InputBar';

interface ChatLeftPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  suggestions: string[];
  onSend: (text: string) => void;
}

export default function ChatLeftPanel({ messages, isStreaming, suggestions, onSend }: ChatLeftPanelProps) {
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
      <MessageThread messages={messages} isStreaming={isStreaming} />
      <InputBar onSend={onSend} isStreaming={isStreaming} suggestions={suggestions} />
    </div>
  );
}
