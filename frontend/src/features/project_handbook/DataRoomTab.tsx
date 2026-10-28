// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The data room: the folder tree of the project's phase model, materialised
// into the document folders. One root folder per management area, the working
// folders of the development and execution phases below it, each with the
// number of documents filed in it.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Folder, FolderOpen, FolderTree } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { useToastStore } from '@/stores/useToastStore';

import { materialiseDataRoom, type DataRoom, type DataRoomFolder } from './api';
import { useDataRoom, useHandbookAction } from './hooks';
import { folderName, refusalText, type TFn } from './labels';

interface Node {
  folder: DataRoomFolder;
  children: Node[];
}

function buildTree(folders: DataRoomFolder[]): Node[] {
  const nodes = new Map<string, Node>(folders.map((f) => [f.id, { folder: f, children: [] }]));
  const roots: Node[] = [];
  for (const node of nodes.values()) {
    const parent = node.folder.parent_id ? nodes.get(node.folder.parent_id) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

function FolderRow({ node, depth, open, toggle, tf }: { node: Node; depth: number; open: Set<string>; toggle: (id: string) => void; tf: TFn }) {
  const { t } = useTranslation();
  const f = node.folder;
  const expanded = open.has(f.id);
  const hasChildren = node.children.length > 0;
  return (
    <>
      <li
        className="flex items-center gap-2 border-b border-border-light px-3 py-1.5 text-sm"
        style={{ paddingLeft: `${12 + depth * 20}px` }}
        data-testid={`data-room-folder-${f.code}`}
      >
        {hasChildren ? (
          <button
            type="button"
            className="text-content-tertiary hover:text-content-primary"
            aria-expanded={expanded}
            aria-label={t('projectHandbook.data_room.toggle', { defaultValue: 'Show or hide subfolders' })}
            onClick={() => toggle(f.id)}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="w-3.5" aria-hidden />
        )}
        {expanded || f.documents > 0 ? (
          <FolderOpen size={15} className="shrink-0 text-oe-blue" aria-hidden />
        ) : (
          <Folder size={15} className="shrink-0 text-content-tertiary" aria-hidden />
        )}
        <span className={depth === 0 ? 'font-medium text-content-primary' : 'text-content-primary'}>{folderName(tf, f)}</span>
        {f.phase_code ? (
          <Badge variant={f.phase_code === 'development' ? 'blue' : 'neutral'} size="sm">
            {t(`projectHandbook.data_room.phase.${f.phase_code}`, { defaultValue: f.phase_code })}
          </Badge>
        ) : null}
        <span className="ml-auto shrink-0 tabular-nums text-xs text-content-secondary">
          {f.documents_total > 0
            ? t('projectHandbook.data_room.docs', { defaultValue: '{{count}} documents', count: f.documents_total })
            : t('projectHandbook.data_room.empty_folder', { defaultValue: 'empty' })}
        </span>
      </li>
      {expanded
        ? node.children.map((c) => (
            <FolderRow key={c.folder.id} node={c} depth={depth + 1} open={open} toggle={toggle} tf={tf} />
          ))
        : null}
    </>
  );
}

function Tree({ room, projectId }: { room: DataRoom; projectId: string }) {
  const { t } = useTranslation();
  const tf = t as TFn;
  const roots = useMemo(() => buildTree(room.folders), [room.folders]);
  const [open, setOpen] = useState<Set<string>>(() => new Set(roots.filter((r) => r.folder.documents_total > 0).map((r) => r.folder.id)));
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const all = room.folders.length;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3" data-testid="data-room-summary">
        {[
          [t('projectHandbook.data_room.folders', { defaultValue: 'Folders' }), all],
          [t('projectHandbook.data_room.documents', { defaultValue: 'Documents filed' }), room.documents - room.unfiled],
          [t('projectHandbook.data_room.unfiled', { defaultValue: 'Not filed yet' }), room.unfiled],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border border-border bg-surface-elevated shadow-sm px-4 py-3">
            <p className="text-xs text-content-tertiary">{label}</p>
            <p className="text-xl font-semibold tabular-nums text-content-primary">{value}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => setOpen(new Set(room.folders.map((f) => f.id)))}>
            {t('projectHandbook.data_room.expand', { defaultValue: 'Expand all' })}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setOpen(new Set())}>
            {t('projectHandbook.data_room.collapse', { defaultValue: 'Collapse all' })}
          </Button>
        </div>
        <Link to={`/projects/${projectId}/files`} className="text-sm text-oe-blue hover:underline">
          {t('projectHandbook.data_room.open_files', { defaultValue: 'Open the document manager' })}
        </Link>
      </div>
      <ul className="overflow-hidden rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid="data-room-tree">
        {roots.map((r) => (
          <FolderRow key={r.folder.id} node={r} depth={0} open={open} toggle={toggle} tf={tf} />
        ))}
      </ul>
    </div>
  );
}

export function DataRoomTab({ projectId, canManage, onChanged }: { projectId: string; canManage: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const query = useDataRoom(projectId, true);
  const materialise = useHandbookAction(
    () => materialiseDataRoom(projectId),
    (result) => {
      addToast({
        type: 'success',
        title: t('projectHandbook.data_room.done', {
          defaultValue: '{{created}} folders created, {{updated}} updated, {{unchanged}} unchanged.',
          created: result.created,
          updated: result.updated,
          unchanged: result.unchanged,
        }),
      });
      onChanged();
      void query.refetch();
    },
  );

  if (query.isLoading) return <SkeletonTable rows={8} columns={2} />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title={t('projectHandbook.data_room.load_failed', { defaultValue: 'The data room could not be loaded' })}
        hint={refusalText(t as TFn, query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }
  const room = query.data;
  const action = (
    <Button
      variant={room.folders.length === 0 ? 'primary' : 'secondary'}
      size="sm"
      icon={<FolderTree size={14} />}
      loading={materialise.isPending}
      disabled={!canManage}
      onClick={() => materialise.mutate()}
      data-testid="data-room-materialise"
    >
      {room.folders.length === 0
        ? t('projectHandbook.data_room.create', { defaultValue: 'Create the folder structure' })
        : t('projectHandbook.data_room.refresh', { defaultValue: 'Bring in line with the phase model' })}
    </Button>
  );
  if (room.folders.length === 0) {
    return (
      <EmptyState
        icon={<FolderTree size={28} />}
        title={t('projectHandbook.data_room.empty_title', { defaultValue: 'The data room has no folders yet' })}
        description={t('projectHandbook.data_room.empty_body', {
          defaultValue: 'The folders of the project phase model, one root folder per management area, become the folder structure of the document manager. Running it again changes nothing that exists.',
        })}
        action={action}
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex justify-end">{action}</div>
      <Tree room={room} projectId={projectId} />
    </div>
  );
}
