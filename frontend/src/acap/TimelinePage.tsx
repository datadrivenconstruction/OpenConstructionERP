import { useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { generateTimeline, downloadTimelineCsv, type TimelineResponse } from './timelineApi';
import { getErrorMessage } from '@/shared/lib/api';
import { GanttChart } from './GanttChart';

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: TimelineResponse };

export default function TimelinePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [state, setState] = useState<LoadState>({ status: 'idle' });
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleGenerate = useCallback(() => {
    if (!projectId) return;
    setState({ status: 'loading' });
    setExportError(null);
    generateTimeline(projectId)
      .then((data) => setState({ status: 'ready', data }))
      .catch((err) => setState({ status: 'error', message: getErrorMessage(err) }));
  }, [projectId]);

  const handleExportCsv = useCallback(() => {
    if (!projectId) return;
    setExporting(true);
    setExportError(null);
    downloadTimelineCsv(projectId)
      .catch((err) => setExportError(getErrorMessage(err)))
      .finally(() => setExporting(false));
  }, [projectId]);

  if (!projectId) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={state.status === 'loading'}
          className="rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {state.status === 'loading' ? 'Menghitung…' : 'Generate Timeline'}
        </button>
        {state.status === 'ready' && (
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={exporting}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-50"
          >
            {exporting ? 'Mengunduh…' : 'Export CSV'}
          </button>
        )}
      </div>

      {exportError && <div className="text-sm text-semantic-error">{exportError}</div>}

      {state.status === 'idle' && (
        <div className="p-6 text-sm text-content-secondary">Belum ada timeline, klik "Generate Timeline".</div>
      )}

      {state.status === 'loading' && (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
        </div>
      )}

      {state.status === 'error' && <div className="p-6 text-sm text-semantic-error">{state.message}</div>}

      {state.status === 'ready' && (
        <GanttChart tasks={state.data.tasks} stages={state.data.stages} totalDays={state.data.total_days} />
      )}
    </div>
  );
}
