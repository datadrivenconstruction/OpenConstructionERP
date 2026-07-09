import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Loader2, ImageOff } from 'lucide-react';
import { generateRender, listRenders, isNotConfiguredError, type RenderResponse } from './renderApi';
import { getErrorMessage, ApiError } from '@/shared/lib/api';

type ListState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; renders: RenderResponse[] };

type GenerateState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'not-configured' }
  | { status: 'no-layout' };

const STATUS_LABEL: Record<string, string> = {
  completed: 'Completed',
  failed: 'Failed',
  pending: 'Pending',
};

export default function RenderPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [listState, setListState] = useState<ListState>({ status: 'loading' });
  const [generateState, setGenerateState] = useState<GenerateState>({ status: 'idle' });

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setListState({ status: 'loading' });
    listRenders(projectId)
      .then((renders) => {
        if (cancelled) return;
        setListState({ status: 'ready', renders });
      })
      .catch((err) => {
        if (cancelled) return;
        setListState({ status: 'error', message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleGenerate = useCallback(() => {
    if (!projectId) return;
    setGenerateState({ status: 'loading' });
    generateRender(projectId)
      .then((render) => {
        setGenerateState({ status: 'idle' });
        setListState((prev) => ({
          status: 'ready',
          renders: [render, ...(prev.status === 'ready' ? prev.renders : [])],
        }));
      })
      .catch((err) => {
        if (isNotConfiguredError(err)) {
          setGenerateState({ status: 'not-configured' });
        } else if (err instanceof ApiError && err.status === 404) {
          setGenerateState({ status: 'no-layout' });
        } else {
          setGenerateState({ status: 'error', message: getErrorMessage(err) });
        }
      });
  }, [projectId]);

  if (!projectId) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={generateState.status === 'loading'}
          className="rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {generateState.status === 'loading' ? 'Rendering… (can take a few minutes)' : 'Generate render'}
        </button>
        {generateState.status === 'loading' && <Loader2 className="h-5 w-5 animate-spin text-oe-blue" />}
      </div>

      {generateState.status === 'not-configured' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
          Render service not configured yet — add GEMINIGEN_API_KEY to enable.
        </div>
      )}

      {generateState.status === 'no-layout' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
          Generate a floor plan first.
        </div>
      )}

      {generateState.status === 'error' && (
        <div className="text-sm text-semantic-error">{generateState.message}</div>
      )}

      {listState.status === 'loading' && (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
        </div>
      )}

      {listState.status === 'error' && <div className="p-6 text-sm text-semantic-error">{listState.message}</div>}

      {listState.status === 'ready' && listState.renders.length === 0 && (
        <div className="p-6 text-sm text-content-secondary">No renders yet, click "Generate render".</div>
      )}

      {listState.status === 'ready' && listState.renders.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {listState.renders.map((render) => (
            <div key={render.render_id} className="rounded-md border border-border p-3" title={render.prompt}>
              {render.status === 'completed' && render.source_url && (
                <img
                  src={render.source_url}
                  alt={`Floor plan v${render.floor_plan_version} render`}
                  className="mb-2 w-full rounded-md object-cover"
                />
              )}
              {render.status === 'completed' && !render.source_url && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
                  <ImageOff className="h-6 w-6" />
                  <span className="ml-2 text-xs">stored (no preview URL)</span>
                </div>
              )}
              {render.status === 'failed' && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary p-2 text-center text-xs text-semantic-error">
                  {render.error_message ?? 'Render failed'}
                </div>
              )}
              {render.status !== 'completed' && render.status !== 'failed' && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              )}
              <div className="flex items-center justify-between text-xs text-content-secondary">
                <span>v{render.floor_plan_version}</span>
                <span>{STATUS_LABEL[render.status] ?? render.status}</span>
              </div>
              <p className="mt-1 truncate text-xs text-content-secondary">{render.prompt}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
