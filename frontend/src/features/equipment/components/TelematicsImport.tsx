// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Telematics import panel: upload an ISO 15143-3 (AEMP 2.0) XML/JSON fleet
 * snapshot or a CSV and see what was accepted, unmatched and rejected.
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { importTelematics, type ImportResult } from '../telematicsApi';
import { importKindFor } from '../telematicsFormat';
import { fmtList } from '@/shared/lib/formatters';

export function TelematicsImport() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const mut = useMutation({
    mutationFn: async (file: File) => {
      const kind = importKindFor(file.name);
      if (!kind) {
        throw new Error(t('equipment.telematics.import_bad_type', { defaultValue: 'Use an XML, JSON or CSV file.' }));
      }
      return importTelematics(kind, file);
    },
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ['equipment', 'telematics'] });
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const rejected = result?.rejected ?? [];
  const tile = (label: string, value: number, tone?: string) => (
    <div className="rounded-lg border border-border-light px-3 py-2">
      <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${tone ?? 'text-content-primary'}`}>{value}</div>
    </div>
  );

  return (
    <Card>
      <CardHeader
        title={t('equipment.telematics.import_title', { defaultValue: 'Import a fleet snapshot' })}
        subtitle={t('equipment.telematics.import_subtitle', {
          defaultValue:
            'ISO 15143-3 (AEMP 2.0) XML or JSON, or a CSV with the columns equipment, recorded_at, engine_hours, idle_hours, fuel_used_l, fuel_level_pct, lat, lng, odometer_km, engine_status, fault_codes.',
        })}
        action={
          <>
            <input
              ref={inputRef}
              type="file"
              accept=".xml,.json,.csv"
              className="hidden"
              aria-label={t('equipment.telematics.import_file', { defaultValue: 'Telematics file' })}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) mut.mutate(f);
                e.target.value = '';
              }}
            />
            <Button
              variant="secondary"
              size="sm"
              icon={<Upload size={14} />}
              loading={mut.isPending}
              onClick={() => inputRef.current?.click()}
            >
              {t('equipment.telematics.import_choose', { defaultValue: 'Choose file' })}
            </Button>
          </>
        }
      />
      <CardContent>
        {!result ? (
          <p className="text-sm text-content-tertiary">
            {t('equipment.telematics.import_hint', {
              defaultValue: 'Machines are matched by their equipment code or serial number.',
            })}
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {tile(
                t('equipment.telematics.import_accepted', { defaultValue: 'Accepted' }),
                result.accepted,
                'text-semantic-success',
              )}
              {tile(
                t('equipment.telematics.import_unmatched', { defaultValue: 'Unmatched' }),
                result.unmatched.length,
                result.unmatched.length > 0 ? 'text-semantic-warning' : undefined,
              )}
              {tile(
                t('equipment.telematics.import_rejected', { defaultValue: 'Rejected' }),
                rejected.length,
                rejected.length > 0 ? 'text-semantic-error' : undefined,
              )}
            </div>
            {result.unmatched.length > 0 && (
              <p className="text-sm text-content-secondary">
                {t('equipment.telematics.import_unmatched_list', {
                  defaultValue: 'No machine with this code or serial: {{refs}}',
                  refs: fmtList(result.unmatched.slice(0, 20)),
                })}
              </p>
            )}
            {rejected.length > 0 && (
              <ul className="space-y-0.5 text-xs text-content-secondary">
                {rejected.slice(0, 20).map((r) => (
                  <li key={`${r.line}-${r.reason}`}>
                    {t('equipment.telematics.import_rejected_row', {
                      defaultValue: 'Line {{line}}: {{reason}}',
                      line: r.line,
                      reason: r.reason,
                    })}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
