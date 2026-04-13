import { useState, useEffect, useRef } from 'react';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface ProjectOption {
  id: string;
  name: string;
}

export default function ProjectSelector() {
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const clearProject = useProjectContextStore((s) => s.clearProject);

  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    apiGet<{ items?: ProjectOption[] }>('/v1/projects/')
      .then((res) => {
        setProjects(res.items ?? (Array.isArray(res) ? (res as ProjectOption[]) : []));
      })
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, [open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const label = activeProjectId ? activeProjectName || 'Project' : 'All Projects';

  return (
    <div ref={dropdownRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 10px',
          background: 'var(--chat-surface-2)',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius-sm)',
          color: 'var(--chat-text-secondary)',
          fontSize: 12,
          fontFamily: 'var(--chat-font-body)',
          cursor: 'pointer',
          maxWidth: 180,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</span>
        <span style={{ fontSize: 8, flexShrink: 0 }}>&#9660;</span>
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: 4,
            minWidth: 200,
            maxHeight: 260,
            overflow: 'auto',
            background: 'var(--chat-surface-2)',
            border: '1px solid var(--chat-border)',
            borderRadius: 'var(--chat-radius)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            zIndex: 100,
          }}
        >
          {/* All Projects option */}
          <button
            type="button"
            onClick={() => {
              clearProject();
              setOpen(false);
            }}
            style={{
              display: 'block',
              width: '100%',
              padding: '8px 12px',
              background: !activeProjectId ? 'var(--chat-surface-3)' : 'transparent',
              border: 'none',
              color: 'var(--chat-text-primary)',
              fontSize: 13,
              fontFamily: 'var(--chat-font-body)',
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            All Projects
          </button>

          <div style={{ height: 1, background: 'var(--chat-border-subtle)' }} />

          {loading && (
            <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--chat-text-tertiary)' }}>Loading...</div>
          )}

          {!loading &&
            projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setActiveProject(p.id, p.name);
                  setOpen(false);
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '8px 12px',
                  background: p.id === activeProjectId ? 'var(--chat-surface-3)' : 'transparent',
                  border: 'none',
                  color: 'var(--chat-text-primary)',
                  fontSize: 13,
                  fontFamily: 'var(--chat-font-body)',
                  cursor: 'pointer',
                  textAlign: 'left',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {p.name}
              </button>
            ))}

          {!loading && projects.length === 0 && (
            <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--chat-text-tertiary)' }}>No projects</div>
          )}
        </div>
      )}
    </div>
  );
}
