// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/** One button: "Download for offline". Saves the open punch items, today's checklists and the crew on the phone. */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Loader2 } from 'lucide-react';
import type { FieldSession } from './fieldApi';
import { downloadForOffline } from './offlinePrefetch';

type State = { kind: 'idle' } | { kind: 'busy' } | { kind: 'done'; count: number } | { kind: 'failed' };

export function OfflineDownloadButton({ session }: { session: FieldSession | null }) {
  const { t } = useTranslation();
  const [state, setState] = useState<State>({ kind: 'idle' });

  const run = async () => {
    if (!session) return;
    setState({ kind: 'busy' });
    const count = await downloadForOffline(session);
    setState(count === null ? { kind: 'failed' } : { kind: 'done', count });
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        data-testid="offline-download"
        onClick={() => void run()}
        disabled={!session || state.kind === 'busy'}
        className="flex h-12 items-center justify-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-4 text-sm font-semibold text-sky-700 disabled:opacity-50"
      >
        {state.kind === 'busy' ? (
          <Loader2 size={18} className="animate-spin" aria-hidden="true" />
        ) : (
          <Download size={18} aria-hidden="true" />
        )}
        {t('field.offline.download', { defaultValue: 'Download for offline' })}
      </button>
      {state.kind === 'done' && (
        <p role="status" data-testid="offline-download-done" className="text-xs text-emerald-700">
          {t('field.offline.downloaded', { count: state.count, defaultValue: 'Saved for offline: {{count}}' })}
        </p>
      )}
      {state.kind === 'failed' && (
        <p role="alert" data-testid="offline-download-failed" className="text-xs text-rose-600">
          {t('field.offline.download_failed', {
            defaultValue: 'Could not download. Try again when you have signal.',
          })}
        </p>
      )}
    </div>
  );
}

export default OfflineDownloadButton;
