import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';

/**
 * A small "open in module" affordance used by the AI Chat read renderers
 * (CONN-80). It turns a deep-link path derived from data already on the wire
 * into a one-click jump to the real module screen, styled with the chat theme
 * tokens (`--chat-*`) so it matches the surrounding panel in both light and
 * dark mode.
 *
 * Navigation uses react-router's `useNavigate` so it works in both chat
 * surfaces (full page + floating panel) without ever touching window.location.
 */
export default function DeepLinkBar({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate();

  return (
    <div
      style={{
        marginTop: 12,
        paddingTop: 10,
        borderTop: '1px solid var(--chat-border-subtle)',
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <button
        type="button"
        onClick={() => navigate(to)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 12px',
          fontSize: 12,
          fontFamily: 'var(--chat-font-body)',
          fontWeight: 500,
          color: 'var(--chat-accent)',
          background: 'var(--chat-surface-1)',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius-sm)',
          cursor: 'pointer',
          transition: 'border-color 0.15s, background 0.15s',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = 'var(--chat-accent)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = 'var(--chat-border-subtle)';
        }}
      >
        {label}
        <ArrowUpRight size={13} strokeWidth={2} />
      </button>
    </div>
  );
}

/** Translated label helper shared by the renderers so copy stays in one place. */
export function useOpenLabels() {
  const { t } = useTranslation();
  return {
    project: t('chat.open_project', { defaultValue: 'Open project' }),
    projects: t('chat.open_projects', { defaultValue: 'Open in Projects' }),
    boq: t('chat.open_boq', { defaultValue: 'Open in BOQ' }),
    schedule: t('chat.open_schedule', { defaultValue: 'Open in 4D Schedule' }),
    validation: t('chat.open_validation', { defaultValue: 'Open Validation' }),
    risk: t('chat.open_risk', { defaultValue: 'Open Risk Register' }),
  };
}
