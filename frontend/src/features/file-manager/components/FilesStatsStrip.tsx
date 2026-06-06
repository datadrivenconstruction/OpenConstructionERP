// FilesStatsStrip — landing-view KPI strip + storage-by-kind breakdown.
//
// Reads off the file tree (no extra API call) so it appears instantly once
// the bootstrap query resolves. Three glance metrics + a colour-coded bar
// that splits total storage across the 8 file kinds. Hidden when the
// project has no files yet (lets the FolderCardGrid empty state breathe).

import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Database, FileText, HardDrive, Layers } from 'lucide-react';
import type { FileKind, FileTreeNode, StorageLocations } from '../types';
import { ALL_KINDS, KIND_COLORS } from '../kindModule';

function fmtBytes(bytes: number): string {
  if (bytes === 0 || !Number.isFinite(bytes)) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const v = bytes / Math.pow(1024, i);
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i] ?? 'TB'}`;
}

interface FilesStatsStripProps {
  tree: FileTreeNode[] | undefined;
  locations: StorageLocations | undefined;
}

export function FilesStatsStrip({ tree, locations }: FilesStatsStripProps) {
  const { t } = useTranslation();

  const stats = useMemo(() => {
    if (!tree || tree.length === 0) return null;
    const totalFiles = tree.reduce((s, n) => s + n.file_count, 0);
    const totalBytes = tree.reduce((s, n) => s + n.total_bytes, 0);
    const populated = tree.filter((n) => n.file_count > 0).length;
    const segments = tree
      .filter((n) => n.total_bytes > 0)
      .map((n) => ({
        kind: n.id as FileKind,
        label: n.label,
        bytes: n.total_bytes,
        pct: totalBytes > 0 ? (n.total_bytes / totalBytes) * 100 : 0,
      }))
      .sort((a, b) => b.bytes - a.bytes);
    return { totalFiles, totalBytes, populated, segments };
  }, [tree]);

  if (!stats || stats.totalFiles === 0) return null;

  const backendRaw = locations?.storage_backend ?? '';
  const backendLabel = backendRaw === 's3'
    ? t('files.stats_backend_s3', { defaultValue: 'S3-compatible' })
    : backendRaw === 'local'
      ? t('files.stats_backend_local', { defaultValue: 'Local disk' })
      : '—';

  return (
    <div className="border-b border-border-light bg-surface-elevated/60">
      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-4 py-3">
        <Metric
          icon={<FileText size={14} />}
          label={t('files.stats_total', { defaultValue: 'Total files' })}
          value={stats.totalFiles.toLocaleString()}
        />
        <Metric
          icon={<HardDrive size={14} />}
          label={t('files.stats_size', { defaultValue: 'Total size' })}
          value={fmtBytes(stats.totalBytes)}
        />
        <Metric
          icon={<Layers size={14} />}
          label={t('files.stats_categories', { defaultValue: 'Categories' })}
          value={`${stats.populated} / ${ALL_KINDS.length}`}
        />
        <Metric
          icon={<Database size={14} />}
          label={t('files.stats_backend', { defaultValue: 'Storage' })}
          value={backendLabel}
        />
      </div>

      {/* Storage breakdown bar — only render when at least one segment has bytes */}
      {stats.segments.length > 0 && (
        <div className="px-4 pb-3">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
              {t('files.stats_breakdown', { defaultValue: 'Storage by category' })}
            </div>
            <div className="text-2xs text-content-quaternary tabular-nums">
              {fmtBytes(stats.totalBytes)}
            </div>
          </div>
          <div
            className="flex h-2 rounded-full overflow-hidden bg-surface-tertiary"
            role="img"
            aria-label={t('files.stats_breakdown', { defaultValue: 'Storage by category' })}
          >
            {stats.segments.map((seg) => (
              <div
                key={seg.kind}
                className={`${KIND_COLORS[seg.kind] ?? 'bg-content-tertiary'} transition-[width] duration-500`}
                style={{ width: `${seg.pct}%` }}
                title={`${seg.label}: ${fmtBytes(seg.bytes)} (${seg.pct.toFixed(1)}%)`}
              />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-2xs">
            {stats.segments.map((seg) => (
              <span
                key={seg.kind}
                className="inline-flex items-center gap-1.5 text-content-tertiary"
              >
                <span
                  className={`h-2 w-2 rounded-full ${KIND_COLORS[seg.kind] ?? 'bg-content-tertiary'}`}
                />
                <span>{seg.label}</span>
                <span className="text-content-quaternary tabular-nums">{seg.pct.toFixed(0)}%</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      <div className="flex items-center gap-1.5 text-2xs font-medium text-content-tertiary uppercase tracking-wider">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-1 text-sm font-semibold text-content-primary tabular-nums truncate">
        {value}
      </div>
    </div>
  );
}
