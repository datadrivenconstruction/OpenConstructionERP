import { useCallback, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { generateTimeline, downloadTimelineCsv } from '@/acap/timelineApi';
import { GanttChart } from '@/acap/GanttChart';
import type { TimelineResponse } from '@/acap/timelineApi';

type TimelineState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: TimelineResponse }
  | { status: 'no-layout' }
  | { status: 'error'; message: string };

interface TimelineStepProps {
  projectId: string;
}

export function TimelineStep({ projectId }: TimelineStepProps) {
  const [state, setState] = useState<TimelineState>({ status: 'idle' });

  const handleGenerate = useCallback(async () => {
    setState({ status: 'loading' });
    try {
      const data = await generateTimeline(projectId);
      setState({ status: 'ready', data });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: 'no-layout' });
      } else {
        setState({ status: 'error', message: getErrorMessage(err) });
      }
    }
  }, [projectId]);

  const handleDownloadCsv = useCallback(async () => {
    try {
      await downloadTimelineCsv(projectId);
    } catch (err) {
      // Error handled by downloadTimelineCsv internals
    }
  }, [projectId]);

  if (state.status === 'no-layout') {
    return (
      <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
        Selesaikan langkah Konfirmasi dulu.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={state.status === 'loading'}
          className="inline-flex items-center gap-2 rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {state.status === 'loading' && <Loader2 size={16} className="animate-spin" />}
          Buat Timeline
        </button>
        {state.status === 'ready' && (
          <button
            type="button"
            onClick={handleDownloadCsv}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
          >
            Download CSV
          </button>
        )}
      </div>

      {state.status === 'error' && (
        <div className="text-sm text-semantic-error">{state.message}</div>
      )}

      {state.status === 'ready' && (
        <>
          <div className="text-lg font-semibold text-content-primary">
            Estimasi durasi: {state.data.total_days} hari kerja
          </div>
          <GanttChart
            tasks={state.data.tasks}
            stages={state.data.stages}
            totalDays={state.data.total_days}
          />
        </>
      )}
    </div>
  );
}

export default TimelineStep;
