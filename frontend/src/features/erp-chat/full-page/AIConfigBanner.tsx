import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { aiApi, type AISettings } from '@/features/ai/api';

/**
 * Banner shown above the chat panel when the user has not configured an
 * AI provider. Without an API key the chat returns a 500-style error and
 * the page feels broken — this banner explains exactly what to do.
 */
export default function AIConfigBanner() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    aiApi
      .getSettings()
      .then((data) => {
        if (!cancelled) setSettings(data);
      })
      .catch(() => {
        // Ignore — we'll show a generic banner if settings call fails
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return null;

  // Determine if any provider has a key set
  const hasKey =
    !!settings &&
    (settings.anthropic_api_key_set ||
      settings.openai_api_key_set ||
      settings.gemini_api_key_set ||
      settings.openrouter_api_key_set ||
      settings.mistral_api_key_set ||
      settings.groq_api_key_set ||
      settings.deepseek_api_key_set ||
      settings.cohere_api_key_set);

  if (hasKey) return null;

  return (
    <div
      style={{
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border)',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        fontFamily: 'var(--chat-font-body)',
        fontSize: 13,
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: 'var(--chat-accent)',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          fontSize: 16,
        }}
      >
        ⚙
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, color: 'var(--chat-text-primary)' }}>
          {t('chat.config_banner_title', { defaultValue: 'AI provider not configured' })}
        </div>
        <div style={{ color: 'var(--chat-text-secondary)', marginTop: 2 }}>
          {t('chat.config_banner_desc', {
            defaultValue:
              'Add an API key (Anthropic / OpenAI / Gemini / OpenRouter / Mistral / Groq) to start chatting with your data.',
          })}
        </div>
      </div>
      <Link
        to="/settings"
        style={{
          flexShrink: 0,
          padding: '8px 14px',
          borderRadius: 'var(--chat-radius)',
          background: 'var(--chat-accent)',
          color: '#ffffff',
          textDecoration: 'none',
          fontWeight: 600,
          fontSize: 12,
          whiteSpace: 'nowrap',
        }}
      >
        {t('chat.open_settings', { defaultValue: 'Open Settings' })}
      </Link>
    </div>
  );
}
