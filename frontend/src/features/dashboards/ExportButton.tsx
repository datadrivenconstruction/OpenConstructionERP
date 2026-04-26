/**
 * ExportButton (T06) — CSV / XLSX / Parquet download trigger.
 *
 * The dropdown surfaces three export formats; clicking one navigates
 * the browser to the streaming export endpoint with the active filters
 * + sort baked into the URL. The Authorization header is attached via
 * a programmatic ``fetch`` + ``Blob`` download so we can reuse the
 * standard Bearer token (an `<a download>` anchor wouldn't carry it).
 */
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, FileSpreadsheet, FileText, Database } from 'lucide-react';

import { Button } from '@/shared/ui';
import { triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  buildSnapshotExportUrl,
  type ExportFormat,
  type SnapshotRowsQuery,
} from './api';

export interface ExportButtonProps {
  snapshotId: string;
  /** Mirrors :class:`DataTable` — same filters/columns get exported. */
  query?: SnapshotRowsQuery;
}

export function ExportButton({ snapshotId, query }: ExportButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ExportFormat | null>(null);
  const toast = useToastStore((s) => s.addToast);

  const handlePick = useCallback(
    async (format: ExportFormat) => {
      setPending(format);
      try {
        const url = buildSnapshotExportUrl(snapshotId, format, query);
        const token = useAuthStore.getState().accessToken;
        const headers: Record<string, string> = {
          'X-DDC-Client': 'OE/1.0',
        };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(url, { method: 'GET', headers });
        if (!resp.ok) {
          throw new Error(`Export failed (HTTP ${resp.status})`);
        }
        const blob = await resp.blob();
        const filename = `snapshot_${snapshotId}.${format}`;
        triggerDownload(blob, filename);
      } catch (err) {
        toast({
          type: 'error',
          title: t('dashboards.export_failed', {
            defaultValue: 'Export failed',
          }),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setPending(null);
        setOpen(false);
      }
    },
    [snapshotId, query, toast, t],
  );

  return (
    <div className="relative inline-block" data-testid="export-button">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        data-testid="export-button-trigger"
      >
        <Download className="mr-1 h-3 w-3" />
        {t('common.export', { defaultValue: 'Export' })}
      </Button>
      {open && (
        <div
          className="absolute right-0 z-30 mt-1 w-44 rounded border border-border-light bg-surface-primary shadow-lg"
          data-testid="export-button-dropdown"
          role="menu"
        >
          <ExportMenuItem
            label="CSV"
            icon={<FileText className="h-3 w-3" />}
            disabled={pending !== null}
            onClick={() => handlePick('csv')}
            testId="export-csv"
          />
          <ExportMenuItem
            label="XLSX"
            icon={<FileSpreadsheet className="h-3 w-3" />}
            disabled={pending !== null}
            onClick={() => handlePick('xlsx')}
            testId="export-xlsx"
          />
          <ExportMenuItem
            label="Parquet"
            icon={<Database className="h-3 w-3" />}
            disabled={pending !== null}
            onClick={() => handlePick('parquet')}
            testId="export-parquet"
          />
        </div>
      )}
    </div>
  );
}

interface ExportMenuItemProps {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  testId: string;
}

function ExportMenuItem({
  label,
  icon,
  onClick,
  disabled,
  testId,
}: ExportMenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-content-primary hover:bg-surface-secondary disabled:opacity-50"
    >
      {icon}
      {label}
    </button>
  );
}
