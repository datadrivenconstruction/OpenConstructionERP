import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, FolderPlus } from 'lucide-react';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { Card, EmptyState } from '@/shared/ui';

interface ProjectRow {
  id: string;
  name: string;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; projects: ProjectRow[] }
  | { status: 'error'; message: string };

export function StudioHomePage() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    apiGet<ProjectRow[]>('/v1/projects/')
      .then((projects) => {
        if (cancelled) return;
        setState({ status: 'ready', projects: projects ?? [] });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ status: 'error', message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-content-primary">ACAP Studio</h1>
        <p className="text-sm text-content-secondary">
          Dari gambar denah ke RAB, timeline, 3D &amp; interior — terpandu.
        </p>
      </div>

      <div>
        <Link
          to="/projects/new"
          className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover"
        >
          <FolderPlus size={16} />
          + Project Baru
        </Link>
      </div>

      {state.status === 'loading' && (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
        </div>
      )}

      {state.status === 'error' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-semantic-error">
          {state.message}
        </div>
      )}

      {state.status === 'ready' && state.projects.length === 0 && (
        <EmptyState
          icon={<FolderPlus size={22} />}
          title="Belum ada project"
          description="Buat project pertama Anda untuk mulai menggunakan ACAP Studio."
        />
      )}

      {state.status === 'ready' && state.projects.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {state.projects.map((p) => (
            <Card key={p.id} padding="md" hoverable>
              <div className="flex flex-col gap-3">
                <div className="text-base font-semibold text-content-primary">{p.name}</div>
                <Link
                  to={`/projects/${p.id}/studio`}
                  className="self-start rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue-hover"
                >
                  Buka Studio
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default StudioHomePage;