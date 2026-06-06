import { useNavigate } from 'react-router-dom';
import { unwrapList } from './normalize';
import { boqPath, readString } from './deepLink';
import DeepLinkBar, { useOpenLabels } from './DeepLinkBar';

interface BOQItem {
  id?: string;
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  unit_rate?: number;
  total?: number;
}

export default function BOQRenderer({ data }: { data: unknown }) {
  const navigate = useNavigate();
  const labels = useOpenLabels();
  // Backend `get_boq_items` returns `{ positions: [...], grand_total, ... }`.
  const items = unwrapList(data, ['positions', 'items']) as BOQItem[];
  // The top-level `boq_id` is on the envelope (not the row list), so read it
  // directly - this is the key that lets a position row deep-link into the BOQ
  // editor. unwrapList intentionally drops everything but the array.
  const boqId = readString(data, 'boq_id');

  if (items.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No BOQ items to display
      </div>
    );
  }

  const grandTotal = items.reduce((sum, it) => sum + (it.total ?? (it.quantity ?? 0) * (it.unit_rate ?? 0)), 0);

  const cellBase: React.CSSProperties = {
    padding: '8px 10px',
    borderBottom: '1px solid var(--chat-border-subtle)',
    fontSize: 13,
    fontFamily: 'var(--chat-font-body)',
    verticalAlign: 'top',
  };

  const numCell: React.CSSProperties = {
    ...cellBase,
    textAlign: 'right',
    fontFamily: 'var(--chat-font-mono)',
    fontVariantNumeric: 'tabular-nums',
  };

  return (
    <div style={{ overflow: 'auto', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', color: 'var(--chat-text-primary)' }}>
        <thead>
          <tr style={{ background: 'var(--chat-surface-2)' }}>
            <th style={{ ...cellBase, fontWeight: 600, width: 60 }}>#</th>
            <th style={{ ...cellBase, fontWeight: 600, textAlign: 'left' }}>Description</th>
            <th style={{ ...cellBase, fontWeight: 600, width: 60, textAlign: 'center' }}>Unit</th>
            <th style={{ ...numCell, fontWeight: 600, width: 80 }}>Qty</th>
            <th style={{ ...numCell, fontWeight: 600, width: 100 }}>Rate</th>
            <th style={{ ...numCell, fontWeight: 600, width: 110 }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => {
            const total = item.total ?? (item.quantity ?? 0) * (item.unit_rate ?? 0);
            const isZeroPrice = (item.unit_rate ?? 0) === 0 && (item.quantity ?? 0) > 0;
            const rowPath = boqPath(boqId, item.id);
            return (
              <tr
                key={item.id ?? item.ordinal ?? i}
                onClick={rowPath ? () => navigate(rowPath) : undefined}
                title={rowPath ? labels.boq : undefined}
                style={{
                  background: i % 2 === 0 ? 'transparent' : 'var(--chat-surface-1)',
                  borderLeft: isZeroPrice ? '3px solid var(--chat-tool-error)' : '3px solid transparent',
                  cursor: rowPath ? 'pointer' : undefined,
                }}
              >
                <td style={{ ...cellBase, color: 'var(--chat-text-tertiary)' }}>{item.ordinal ?? i + 1}</td>
                <td style={cellBase}>{item.description ?? '-'}</td>
                <td style={{ ...cellBase, textAlign: 'center', color: 'var(--chat-text-secondary)' }}>{item.unit ?? '-'}</td>
                <td style={numCell}>{item.quantity != null ? item.quantity.toLocaleString() : '-'}</td>
                <td style={{ ...numCell, color: isZeroPrice ? 'var(--chat-tool-error)' : undefined }}>
                  {item.unit_rate != null ? item.unit_rate.toLocaleString(undefined, { minimumFractionDigits: 2 }) : '-'}
                </td>
                <td style={numCell}>{total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr style={{ background: 'var(--chat-surface-2)' }}>
            <td colSpan={5} style={{ ...cellBase, fontWeight: 600, textAlign: 'right', paddingRight: 16 }}>
              Grand Total
            </td>
            <td style={{ ...numCell, fontWeight: 700, color: 'var(--chat-accent)', fontSize: 14 }}>
              {grandTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </td>
          </tr>
        </tfoot>
      </table>
      {boqPath(boqId) && (
        <div style={{ padding: '0 10px 10px' }}>
          <DeepLinkBar to={boqPath(boqId)!} label={labels.boq} />
        </div>
      )}
    </div>
  );
}
