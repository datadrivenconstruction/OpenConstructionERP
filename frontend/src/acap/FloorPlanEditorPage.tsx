import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { getLatestLayout, saveLayout, LayoutValidationApiError } from './floorPlanApi';
import { getErrorMessage } from '@/shared/lib/api';
import type { FloorPlan } from './planTypes';
import { FloorPlanEditor } from './FloorPlanEditor';

type LoadState =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'error'; message: string }
  | { status: 'ready'; plan: FloorPlan; version: number };

export default function FloorPlanEditorPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [saving, setSaving] = useState(false);
  const [saveErrors, setSaveErrors] = useState<string[] | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setState({ status: 'loading' });
    getLatestLayout(projectId)
      .then((res) => {
        if (cancelled) return;
        setState({ status: 'ready', plan: res.plan, version: res.version });
      })
      .catch((err) => {
        if (cancelled) return;
        const status = (err as { status?: number }).status;
        if (status === 404) {
          setState({ status: 'empty' });
        } else {
          setState({ status: 'error', message: getErrorMessage(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleChange = useCallback((plan: FloorPlan) => {
    setState((prev) => (prev.status === 'ready' ? { ...prev, plan } : prev));
    setSaveErrors(null);
  }, []);

  const handleSave = useCallback(() => {
    if (!projectId || state.status !== 'ready') return;
    setSaving(true);
    setSaveErrors(null);
    saveLayout(projectId, state.plan)
      .then((res) => {
        setState({ status: 'ready', plan: res.plan, version: res.version });
        setSavedVersion(res.version);
      })
      .catch((err) => {
        if (err instanceof LayoutValidationApiError) {
          setSaveErrors(err.reasons);
        } else {
          setSaveErrors([getErrorMessage(err)]);
        }
      })
      .finally(() => setSaving(false));
  }, [projectId, state]);

  if (!projectId) return null;

  if (state.status === 'loading') {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
      </div>
    );
  }

  if (state.status === 'empty') {
    return <div className="p-6 text-content-secondary">Belum ada layout, generate dulu.</div>;
  }

  if (state.status === 'error') {
    return <div className="p-6 text-semantic-error">{state.message}</div>;
  }

  return (
    <div className="p-4">
      <FloorPlanEditor
        plan={state.plan}
        onChange={handleChange}
        onSave={handleSave}
        saving={saving}
        saveErrors={saveErrors}
        savedVersion={savedVersion}
      />
    </div>
  );
}
