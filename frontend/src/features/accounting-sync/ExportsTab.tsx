// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Exports tab: pick the period, then download the file the accountant asks for.
 * The buttons are the export kinds the connection's provider and chart template
 * support; a German chart (datev_extf) unlocks the two DATEV files.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  downloadExport,
  exportKindsFor,
  useTemplates,
  useSyncMutation,
  type Connection,
  type DateRange,
  type ExportKind,
} from './api';
import { exportLabel } from './labels';
import { PeriodPicker } from './PeriodPicker';

const PROVIDER_KINDS: Record<string, ExportKind[] | undefined> = {
  datev: ['datev_postings', 'datev_master'],
  journal: ['journal_csv', 'journal_xlsx'],
  saft: ['saft'],
};

/** Pure: the export kinds offered for a connection. Exported for the tests. */
export function availableExports(
  connection: Pick<Connection, 'provider' | 'chart_template'>,
  templates: { key: string; formats: string[] }[],
  allKinds: ExportKind[],
): ExportKind[] {
  const byProvider = PROVIDER_KINDS[connection.provider] ?? allKinds;
  const tpl = templates.find((x) => x.key === connection.chart_template);
  const byTemplate = exportKindsFor(tpl?.formats, allKinds);
  const both = byProvider.filter((k) => byTemplate.includes(k));
  return both.length > 0 ? both : byProvider.filter((k) => allKinds.includes(k));
}

export function ExportsTab({
  connection,
  range,
  onRange,
}: {
  connection: Connection;
  range: DateRange;
  onRange: (r: DateRange) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const catalogQ = useTemplates(connection.country_code ?? '');
  const [busyKind, setBusyKind] = useState<ExportKind | null>(null);
  // An export lands in the sync log, so it refreshes the same cache as a push.
  const exportMut = useSyncMutation((kind: ExportKind) => {
    const cols = connection.settings.journal_columns;
    return downloadExport(connection.id, kind, range, kind.startsWith('journal') ? cols : undefined);
  });

  const catalog = catalogQ.data;
  const kinds = catalog ? availableExports(connection, catalog.templates, catalog.export_kinds) : [];

  return (
    <div className="space-y-4" data-testid="accounting-sync-exports">
      <Card padding="md">
        <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('accountingSync.exports.period', { defaultValue: 'Period' })}</h3>
        <PeriodPicker range={range} onChange={onRange} />
        <p className="mt-2 text-xs text-content-tertiary">
          {t('accountingSync.exports.period_hint', { defaultValue: 'Leave a date empty to start or end at the first or last document.' })}
        </p>
      </Card>

      <Card padding="md">
        <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('accountingSync.exports.files', { defaultValue: 'Files' })}</h3>
        {catalogQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</p>
        ) : kinds.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('accountingSync.exports.none', { defaultValue: 'This connection has no file export. Live connections send documents from the Sync tab.' })}
          </p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {kinds.map((kind) => (
              <Button
                key={kind}
                variant="secondary"
                icon={<Download size={14} />}
                loading={exportMut.isPending && busyKind === kind}
                disabled={exportMut.isPending}
                data-testid={`export-${kind}`}
                onClick={() => {
                  setBusyKind(kind);
                  exportMut.mutate(kind, {
                    onError: (err) =>
                      addToast({
                        type: 'error',
                        title: t('accountingSync.exports.failed', { defaultValue: 'Export failed' }),
                        message: getErrorMessage(err),
                      }),
                  });
                }}
              >
                {exportLabel(t, kind)}
              </Button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
