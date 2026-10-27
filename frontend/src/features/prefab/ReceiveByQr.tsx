// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Book a delivered unit in on site: scan its QR label (a scanner types the
 * code into the first field) and enter the delivery note it came with. Only a
 * dispatched unit can be received; the server says why otherwise.
 */
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { QrCode } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { receivePrefabUnitByQr } from './api';

export function ReceiveByQr({ onReceived }: { onReceived: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [token, setToken] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token.trim() || !note.trim()) return;
    setBusy(true);
    try {
      const unit = await receivePrefabUnitByQr({ qr_token: token.trim(), delivery_note_ref: note.trim() });
      addToast({
        type: 'success',
        title: t('prefab.received', { defaultValue: 'Unit received' }),
        message: unit.ref,
      });
      setToken('');
      setNote('');
      onReceived();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('prefab.receive_failed', { defaultValue: 'Could not receive the unit' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="flex flex-wrap items-end gap-2 rounded-xl border border-border-light bg-surface-elevated p-3"
      data-testid="prefab-receive-qr"
    >
      <QrCode size={18} className="mb-2 text-oe-blue" aria-hidden />
      <label className="flex min-w-[12rem] flex-1 flex-col text-2xs text-content-tertiary">
        {t('prefab.receive_qr_label', { defaultValue: 'Scanned QR code' })}
        <input
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mt-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1 font-mono text-sm text-content-primary"
        />
      </label>
      <label className="flex min-w-[10rem] flex-col text-2xs text-content-tertiary">
        {t('prefab.field_delivery_note', { defaultValue: 'Delivery note' })}
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="mt-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
        />
      </label>
      <button
        type="submit"
        disabled={busy || !token.trim() || !note.trim()}
        className="rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
      >
        {t('prefab.receive_submit', { defaultValue: 'Book delivery' })}
      </button>
    </form>
  );
}
