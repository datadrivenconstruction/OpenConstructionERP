// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Scan against design: compare the selected scan with a design surface, read
 * the deviation statistics and heatmap, export them, and turn the difference
 * into a cut/fill volume that a person confirms before it reaches the BOQ.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Flame, Layers, Ruler } from 'lucide-react';
import { Badge, Button, Card, StatCard } from '@/shared/ui';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { confirmVolume, listSurfaces, type Finding, type Volume } from '@/features/survey/volumesApi';
import { SendToBoqDialog } from '@/features/survey/VolumeDialogs';
import { listProfiles } from '@/features/setting-out/api';
import {
  createCutFill,
  deviationExportUrl,
  listDeviationReports,
  previewCutFill,
  runDeviation,
  type CutFillCreated,
  type CutFillInput,
  type CutFillPreview,
  type DeviationReport,
} from './scanDesignApi';
import { acknowledgeable, BAND_ORDER, bandColor, bandRange, fmtMm, hasBlockingFinding, outShare, verticalProfiles } from './scanDesign';

interface Props {
  scanId: string;
  projectId: string;
  heatReportId: string | null;
  onHeatmap: (reportId: string | null) => void;
}

const SEVERITY_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'neutral'> = {
  within: 'success',
  warning: 'warning',
  over: 'error',
};

function FindingList({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null;
  return (
    <ul className="space-y-1.5" data-testid="scan-design-findings">
      {findings.map((f) => (
        <li key={f.rule_id + f.message} className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-xs">
          <span className={f.severity === 'error' ? 'font-semibold text-semantic-error' : 'font-semibold text-semantic-warning'}>{f.rule_id}</span>{' '}
          <span className="text-content-primary">{f.message}</span>
          {f.suggestion && <p className="mt-0.5 text-content-tertiary">{f.suggestion}</p>}
        </li>
      ))}
    </ul>
  );
}

export function ScanDesignPanel({ scanId, projectId, heatReportId, onHeatmap }: Props) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });

  const surfaces = useQuery({ queryKey: ['volumes', 'surfaces', projectId], queryFn: () => listSurfaces(projectId), enabled: !!projectId, retry: false });
  const profiles = useQuery({ queryKey: ['setting-out', 'profiles', projectId], queryFn: () => listProfiles(projectId), enabled: !!projectId, retry: false });
  const reports = useQuery({ queryKey: ['pointcloud', 'deviation', scanId, lang], queryFn: () => listDeviationReports(scanId, lang), retry: false });

  const tolerances = useMemo(() => verticalProfiles(profiles.data ?? []), [profiles.data]);
  const [surfaceId, setSurfaceId] = useState('');
  const [toleranceKey, setToleranceKey] = useState('demo');
  const [threshold, setThreshold] = useState('5');
  const [groundOnly, setGroundOnly] = useState(true);
  const [reportId, setReportId] = useState<string | null>(null);

  const list = reports.data ?? [];
  const report: DeviationReport | undefined = list.find((r) => r.id === reportId) ?? list[0];
  useEffect(() => {
    const first = surfaces.data?.[0];
    if (!surfaceId && first) setSurfaceId(report?.surface_id ?? first.id);
  }, [surfaces.data, surfaceId, report]);
  useEffect(() => {
    const first = tolerances[0];
    if (first && !tolerances.some((p) => p.key === toleranceKey)) setToleranceKey(first.key);
  }, [tolerances, toleranceKey]);

  const compare = useMutation({
    mutationFn: () =>
      runDeviation(scanId, { surface_id: surfaceId, tolerance_key: toleranceKey, ground_only: groundOnly, threshold_pct: Number(threshold) || 0 }, lang),
    onSuccess: (r) => {
      setReportId(r.id);
      void qc.invalidateQueries({ queryKey: ['pointcloud', 'deviation', scanId] });
      onHeatmap(r.id);
    },
    onError: fail,
  });

  // ── Cut and fill ──────────────────────────────────────────────────────
  const [cell, setCell] = useState('0.5');
  const [method, setMethod] = useState<'grid' | 'tin'>('grid');
  const [preview, setPreview] = useState<CutFillPreview | null>(null);
  const [created, setCreated] = useState<CutFillCreated | null>(null);
  const [confirmed, setConfirmed] = useState<Volume | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const cutInput = (): CutFillInput => ({ surface_id: surfaceId, cell_size_m: Number(cell) || 0.5, stat: 'min', ground_only: groundOnly, method });
  const reset = () => {
    setPreview(null);
    setCreated(null);
    setConfirmed(null);
  };
  const doPreview = useMutation({ mutationFn: () => previewCutFill(scanId, cutInput()), onSuccess: (p) => { reset(); setPreview(p); }, onError: fail });
  const doCreate = useMutation({ mutationFn: () => createCutFill(scanId, cutInput(), lang), onSuccess: setCreated, onError: fail });
  const doConfirm = useMutation({
    mutationFn: () => confirmVolume(created!.volume_id, acknowledgeable(created!.findings), lang),
    onSuccess: (v) => {
      setConfirmed(v);
      void qc.invalidateQueries({ queryKey: ['volumes'] });
    },
    onError: fail,
  });

  // The surfaces module is off or the project has no access: the panel stays out of the way.
  if (surfaces.isError || (surfaces.isSuccess && surfaces.data.length === 0 && !list.length)) {
    return surfaces.isSuccess ? (
      <Card>
        <p className="text-sm text-content-tertiary" data-testid="scan-design-no-surface">
          {t('pointcloud.design.no_surface', { defaultValue: 'Add a design surface under Survey volumes to compare this scan with the design.' })}
        </p>
      </Card>
    ) : null;
  }

  const s = report?.stats;
  const tol = report?.tolerance.v_mm ?? 0;
  const share = s ? outShare(s) : null;

  return (
    <Card data-testid="scan-design-panel">
      <div className="space-y-4">
        <div>
          <h2 className="oe-card-title">{t('pointcloud.design.title', { defaultValue: 'Scan against design' })}</h2>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('pointcloud.design.subtitle', {
              defaultValue: 'Height of every scan point above or below the design surface, checked against the tolerance of a setting-out profile.',
            })}
          </p>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <label className="space-y-1 text-xs text-content-secondary">
            <span>{t('pointcloud.design.surface', { defaultValue: 'Design surface' })}</span>
            <select className="oe-input w-full" value={surfaceId} onChange={(e) => { setSurfaceId(e.target.value); reset(); }} data-testid="scan-design-surface">
              {(surfaces.data ?? []).map((x) => (
                <option key={x.id} value={x.id}>{`${x.code} ${x.name}`}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs text-content-secondary">
            <span>{t('pointcloud.design.tolerance', { defaultValue: 'Tolerance profile' })}</span>
            <select className="oe-input w-full" value={toleranceKey} onChange={(e) => setToleranceKey(e.target.value)}>
              {tolerances.map((p) => (
                <option key={p.key} value={p.key}>{`${p.name} (±${fmtMm(p.vMm)} mm)`}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs text-content-secondary">
            <span>{t('pointcloud.design.threshold', { defaultValue: 'Flag when more than this share is out (%)' })}</span>
            <input className="oe-input w-full" inputMode="decimal" dir="ltr" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </label>
          <label className="inline-flex items-center gap-2 self-end pb-2 text-xs text-content-secondary">
            <input type="checkbox" checked={groundOnly} onChange={(e) => setGroundOnly(e.target.checked)} />
            {t('pointcloud.design.ground_only', { defaultValue: 'Ground points only (class 2)' })}
          </label>
          <div className="self-end">
            <Button
              className="w-full"
              icon={<Ruler size={14} />}
              loading={compare.isPending}
              disabled={!surfaceId || !tolerances.length}
              onClick={() => compare.mutate()}
              data-testid="scan-design-compare"
            >
              {t('pointcloud.design.compare', { defaultValue: 'Compare' })}
            </Button>
          </div>
        </div>

        {list.length > 1 && (
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            <span>{t('pointcloud.design.report', { defaultValue: 'Comparison' })}</span>
            <select className="oe-input" value={report?.id ?? ''} onChange={(e) => { setReportId(e.target.value); if (heatReportId) onHeatmap(e.target.value); }}>
              {list.map((r) => (
                <option key={r.id} value={r.id}>{`${r.surface_code} · ±${fmtMm(r.tolerance.v_mm)} mm · ${r.created_at?.slice(0, 16).replace('T', ' ') ?? ''}`}</option>
              ))}
            </select>
          </label>
        )}

        {report && s && (
          <div className="space-y-3" data-testid="scan-design-report">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={SEVERITY_VARIANT[report.severity] ?? 'neutral'} size="sm">
                {t(`pointcloud.design.severity_${report.severity}`, { defaultValue: report.severity })}
              </Badge>
              <span className="text-xs text-content-tertiary">
                {t('pointcloud.design.against', {
                  defaultValue: '{{surface}} · {{profile}} ±{{tol}} mm · {{compared}} of {{read}} points',
                  surface: `${report.surface_code} ${report.surface_name}`,
                  profile: report.tolerance.label,
                  tol: fmtMm(tol),
                  compared: s.points_compared.toLocaleString(lang),
                  read: s.points_read.toLocaleString(lang),
                })}
              </span>
              {report.used_all_classes && (
                <span className="text-xs text-semantic-warning">
                  {t('pointcloud.design.all_classes', { defaultValue: 'The scan has no ground class, so every point was compared.' })}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <StatCard size="sm" label={t('pointcloud.design.mean', { defaultValue: 'Mean' })} value={`${fmtMm(s.mean_mm)} mm`} />
              <StatCard size="sm" label={t('pointcloud.design.rms', { defaultValue: 'RMS' })} value={`${fmtMm(s.rms_mm)} mm`} tone={s.rms_mm != null && s.rms_mm > tol ? 'danger' : 'default'} />
              <StatCard size="sm" label={t('pointcloud.design.p95', { defaultValue: 'P95 of |deviation|' })} value={`${fmtMm(s.p95_mm)} mm`} />
              <StatCard
                size="sm"
                label={t('pointcloud.design.within', { defaultValue: 'Within tolerance' })}
                value={`${fmtMm(s.within_pct)} %`}
                sub={share != null ? t('pointcloud.design.out_share', { defaultValue: '{{share}} % out', share: fmtMm(share, 2) }) : undefined}
                tone={share != null && share > report.threshold_pct ? 'warning' : 'success'}
              />
              <StatCard size="sm" label={t('pointcloud.design.coverage', { defaultValue: 'Design covered' })} value={`${fmtMm(s.coverage_pct)} %`} />
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary" data-testid="scan-design-legend">
              {BAND_ORDER.filter((b) => b !== 'none' || s.bands.none > 0).map((b) => (
                <span key={b} className="inline-flex items-center gap-1.5">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: bandColor(b) }} aria-hidden="true" />
                  {b === 'none' ? t('pointcloud.design.band_none', { defaultValue: 'Not compared' }) : `${bandRange(b, tol)} mm`}
                  <span className="tabular-nums text-content-tertiary">{s.bands[b].toLocaleString(lang)}</span>
                </span>
              ))}
            </div>

            <FindingList findings={report.findings} />

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={heatReportId === report.id ? 'primary' : 'secondary'}
                icon={<Flame size={14} />}
                onClick={() => onHeatmap(heatReportId === report.id ? null : report.id)}
                data-testid="scan-design-heatmap"
              >
                {heatReportId === report.id
                  ? t('pointcloud.design.hide_heatmap', { defaultValue: 'Show scan colours' })
                  : t('pointcloud.design.show_heatmap', { defaultValue: 'Show deviation heatmap' })}
              </Button>
              <Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={() => void downloadWithAuth(deviationExportUrl(report.id, 'pdf', lang), `deviation-${report.surface_code}.pdf`).catch(fail)}>
                PDF
              </Button>
              <Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={() => void downloadWithAuth(deviationExportUrl(report.id, 'csv', lang), `deviation-${report.surface_code}.csv`).catch(fail)}>
                CSV
              </Button>
            </div>
          </div>
        )}

        <div className="space-y-3 border-t border-border-light pt-4">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">{t('pointcloud.cutfill.title', { defaultValue: 'Cut and fill to the design' })}</h3>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('pointcloud.cutfill.subtitle', {
                defaultValue: 'Cut is scan above the design, fill is scan below it. Preview, create a draft volume, check it, then send it to a BOQ position.',
              })}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="space-y-1 text-xs text-content-secondary">
              <span>{t('pointcloud.cutfill.cell', { defaultValue: 'Cell size (m)' })}</span>
              <input className="oe-input w-24" inputMode="decimal" dir="ltr" value={cell} onChange={(e) => { setCell(e.target.value); reset(); }} />
            </label>
            <label className="space-y-1 text-xs text-content-secondary">
              <span>{t('pointcloud.cutfill.method', { defaultValue: 'Method' })}</span>
              <select className="oe-input" value={method} onChange={(e) => { setMethod(e.target.value as 'grid' | 'tin'); reset(); }}>
                <option value="grid">{t('pointcloud.cutfill.method_grid', { defaultValue: 'Grid' })}</option>
                <option value="tin">{t('pointcloud.cutfill.method_tin', { defaultValue: 'TIN to TIN' })}</option>
              </select>
            </label>
            <Button size="sm" variant="secondary" icon={<Layers size={14} />} loading={doPreview.isPending} disabled={!surfaceId} onClick={() => doPreview.mutate()} data-testid="scan-cutfill-preview">
              {t('pointcloud.cutfill.preview', { defaultValue: 'Preview' })}
            </Button>
          </div>

          {preview && (
            <div className="space-y-2" data-testid="scan-cutfill-result">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatCard size="sm" label={t('pointcloud.cutfill.cut', { defaultValue: 'Cut' })} value={`${fmtMm(preview.cut_m3, 2)} m³`} />
                <StatCard size="sm" label={t('pointcloud.cutfill.fill', { defaultValue: 'Fill' })} value={`${fmtMm(preview.fill_m3, 2)} m³`} />
                <StatCard size="sm" label={t('pointcloud.cutfill.net', { defaultValue: 'Net (cut minus fill)' })} value={`${fmtMm(preview.net_m3, 2)} m³`} />
                <StatCard size="sm" label={t('pointcloud.design.coverage', { defaultValue: 'Design covered' })} value={`${fmtMm(preview.coverage_pct)} %`} />
              </div>
              {created && <FindingList findings={created.findings} />}
              <div className="flex flex-wrap items-center gap-2">
                {!created && (
                  <Button size="sm" loading={doCreate.isPending} onClick={() => doCreate.mutate()} data-testid="scan-cutfill-create">
                    {t('pointcloud.cutfill.create', { defaultValue: 'Create draft volume' })}
                  </Button>
                )}
                {created && !confirmed && (
                  <>
                    <span className="text-xs text-content-secondary">
                      {t('pointcloud.cutfill.created', { defaultValue: 'Draft {{code}} created. Check the numbers and the findings, then confirm.', code: created.volume_code })}
                    </span>
                    <Button size="sm" loading={doConfirm.isPending} disabled={hasBlockingFinding(created.findings)} onClick={() => doConfirm.mutate()} data-testid="scan-cutfill-confirm">
                      {acknowledgeable(created.findings).length
                        ? t('pointcloud.cutfill.confirm_ack', { defaultValue: 'I checked the warnings, confirm' })
                        : t('pointcloud.cutfill.confirm', { defaultValue: 'Confirm volume' })}
                    </Button>
                  </>
                )}
                {confirmed && (
                  <Button size="sm" onClick={() => setSendOpen(true)} data-testid="scan-cutfill-send">
                    {t('pointcloud.cutfill.send', { defaultValue: 'Send to BOQ position' })}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      {confirmed && (
        <SendToBoqDialog
          open={sendOpen}
          projectId={projectId}
          volume={confirmed}
          onClose={() => setSendOpen(false)}
          onSent={() => {
            setSendOpen(false);
            addToast({ type: 'success', title: t('pointcloud.cutfill.sent', { defaultValue: 'Quantity sent to the BOQ.' }) });
          }}
        />
      )}
    </Card>
  );
}
