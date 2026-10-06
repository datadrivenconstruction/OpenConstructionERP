// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';

/** Persistent identity, separate from editable titles and dismissible setup tips. */
export function AiDisclosure({ id }: { id?: string }) {
  const { t } = useTranslation();
  return (
    <p
      id={id}
      data-testid="chat-ai-disclosure"
      style={{
        margin: 0,
        padding: '8px 16px',
        flexShrink: 0,
        fontSize: 13,
        fontWeight: 600,
        lineHeight: 1.5,
        overflowWrap: 'anywhere',
        color: 'var(--chat-text-primary)',
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border)',
      }}
    >
      {t('chat.panel.title_default', { defaultValue: 'AI assistant' })}
    </p>
  );
}
