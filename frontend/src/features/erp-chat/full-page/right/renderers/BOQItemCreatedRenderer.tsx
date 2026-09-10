// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { toNum } from './normalize';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/**
 * Renders the `boq_item_created` write-tool result (`create_boq_item`):
 * a confirmation card for the newly created BOQ position with a deep-link
 * into the BOQ module so the user can review the persisted row.
 */
interface CreatedItem {
  id?: string;
  boq_id?: string;
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  unit_rate?: number;
  total?: number;
}

function num(v: number | undefined, digits = 2): string {
  const n = toNum(v);
  if (n == null) return '-';
  return n.toLocaleString(getNumberLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export default function BOQItemCreatedRenderer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const it = (data && typeof data === 'object' && !Array.isArray(data) ? data : {}) as CreatedItem;

  if (!it.id && !it.description) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        {t('erp_chat.boq_item_created.no_details', { defaultValue: 'No item details' })}
      </div>
    );
  }

  const row: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '8px 0',
    borderBottom: '1px solid var(--chat-border-subtle)',
    fontSize: 13,
  };
  const numCell: React.CSSProperties = { fontFamily: 'var(--chat-font-mono)', fontVariantNumeric: 'tabular-nums' };

  return (
    <div style={{ padding: 16, fontFamily: 'var(--chat-font-body)' }}>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 12,
          fontFamily: 'var(--chat-font-mono)',
          color: 'var(--chat-tool-done)',
          marginBottom: 12,
        }}
      >
        <span>&#10003;</span> {t('erp_chat.boq_item_created.position_created', { defaultValue: 'Position created' })}
      </div>

      <div
        style={{
          background: 'var(--chat-surface-1)',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius)',
          padding: '4px 14px',
        }}
      >
        {it.ordinal && (
          <div style={row}>
            <span style={{ color: 'var(--chat-text-tertiary)' }}>{t('erp_chat.boq_item_created.ordinal', { defaultValue: 'Ordinal' })}</span>
            <span style={numCell}>{it.ordinal}</span>
          </div>
        )}
        <div style={row}>
          <span style={{ color: 'var(--chat-text-tertiary)' }}>{t('erp_chat.boq_item_created.description', { defaultValue: 'Description' })}</span>
          <span style={{ textAlign: 'right', maxWidth: '70%' }}>{it.description ?? '-'}</span>
        </div>
        <div style={row}>
          <span style={{ color: 'var(--chat-text-tertiary)' }}>{t('erp_chat.boq_item_created.unit', { defaultValue: 'Unit' })}</span>
          <span>{it.unit ?? '-'}</span>
        </div>
        <div style={row}>
          <span style={{ color: 'var(--chat-text-tertiary)' }}>{t('erp_chat.boq_item_created.quantity', { defaultValue: 'Quantity' })}</span>
          <span style={numCell}>{num(it.quantity)}</span>
        </div>
        <div style={row}>
          <span style={{ color: 'var(--chat-text-tertiary)' }}>{t('erp_chat.boq_item_created.unit_rate', { defaultValue: 'Unit rate' })}</span>
          <span style={numCell}>{num(it.unit_rate)}</span>
        </div>
        <div style={{ ...row, borderBottom: 'none' }}>
          <span style={{ fontWeight: 600 }}>{t('erp_chat.boq_item_created.total', { defaultValue: 'Total' })}</span>
          <span style={{ ...numCell, fontWeight: 700, color: 'var(--chat-accent)' }}>{num(it.total)}</span>
        </div>
      </div>

      {it.boq_id && (
        <a
          href={`/boq/${it.boq_id}`}
          style={{
            display: 'inline-block',
            marginTop: 12,
            fontSize: 12,
            color: 'var(--chat-accent)',
            textDecoration: 'underline',
            fontWeight: 500,
          }}
        >
          {t('erp_chat.boq_item_created.open_in_editor', { defaultValue: 'Open in BOQ editor' })} →
        </a>
      )}
    </div>
  );
}
