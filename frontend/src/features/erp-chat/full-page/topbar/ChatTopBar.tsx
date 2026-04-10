import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ProjectSelector from './ProjectSelector';

interface ChatTopBarProps {
  onClear: () => void;
}

export default function ChatTopBar({ onClear }: ChatTopBarProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  return (
    <div
      style={{
        height: 'var(--chat-topbar-h)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 16px',
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border-subtle)',
        fontFamily: 'var(--chat-font-body)',
        flexShrink: 0,
      }}
    >
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate('/')}
        aria-label={t('chat.back_to_dashboard', { defaultValue: 'Back to dashboard' })}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          background: 'none',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius-sm)',
          color: 'var(--chat-text-secondary)',
          cursor: 'pointer',
          fontSize: 16,
          flexShrink: 0,
          transition: 'border-color 0.15s, color 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-border)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-primary)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-border-subtle)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-secondary)';
        }}
      >
        &#8592;
      </button>

      {/* Title */}
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: 'var(--chat-text-primary)',
          flex: 1,
        }}
      >
        {t('chat.title', { defaultValue: 'ERP AI Assistant' })}
      </div>

      {/* Project selector */}
      <ProjectSelector />

      {/* Clear button */}
      <button
        type="button"
        onClick={onClear}
        aria-label={t('chat.clear_chat', { defaultValue: 'Clear chat' })}
        title={t('chat.clear_chat', { defaultValue: 'Clear chat' })}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          background: 'none',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius-sm)',
          color: 'var(--chat-text-secondary)',
          cursor: 'pointer',
          fontSize: 14,
          flexShrink: 0,
          transition: 'border-color 0.15s, color 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-tool-error)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-tool-error)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-border-subtle)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--chat-text-secondary)';
        }}
      >
        &#128465;
      </button>
    </div>
  );
}
