// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Compact readout of a photo evidence record: grade, where (with accuracy and
 * source), when (with source), which way the camera faced, and the file hash.
 */
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Clock, Compass, Fingerprint, MapPin, ShieldCheck, ShieldAlert } from 'lucide-react';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';
import { compassPoint, type PhotoEvidence } from '@/shared/lib/photoEvidence';

interface EvidenceBadgeProps {
  evidence: PhotoEvidence | null | undefined;
  /** One line (thumbnail overlay) or the full list (detail view). */
  compact?: boolean;
  className?: string;
}

export function EvidenceBadge({ evidence, compact = false, className }: EvidenceBadgeProps) {
  const { t } = useTranslation();
  if (!evidence) {
    return (
      <span className={clsx('inline-flex items-center gap-1 text-[10px] text-content-tertiary', className)}>
        <ShieldAlert size={11} />
        {t('field_evidence.none', { defaultValue: 'No capture evidence' })}
      </span>
    );
  }
  const full = evidence.grade === 'full';
  const gradeLabel = full
    ? t('field_evidence.grade_full', { defaultValue: 'Located and timed' })
    : t('field_evidence.grade_basic', { defaultValue: 'Hashed, not located' });
  const loc = evidence.location;
  const sourceLabel = (source: string | undefined) =>
    source === 'device'
      ? t('field_evidence.source_device', { defaultValue: 'device' })
      : source === 'exif'
        ? t('field_evidence.source_exif', { defaultValue: 'camera' })
        : t('field_evidence.source_server', { defaultValue: 'upload time' });

  if (compact) {
    return (
      <span
        className={clsx(
          'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
          full ? 'bg-emerald-600/90 text-white' : 'bg-amber-500/90 text-white',
          className,
        )}
        title={gradeLabel}
        data-testid="evidence-badge"
      >
        {full ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
        {loc && loc.accuracy_m != null
          ? t('field_evidence.accuracy_short', {
              defaultValue: '±{{meters}} m',
              meters: fmtNumber(loc.accuracy_m, 0),
            })
          : gradeLabel}
      </span>
    );
  }

  const heading = evidence.orientation?.heading_deg;
  const compassLabel = (point: string): string => {
    switch (point) {
      case 'N':
        return t('field_evidence.compass_n', { defaultValue: 'N' });
      case 'NE':
        return t('field_evidence.compass_ne', { defaultValue: 'NE' });
      case 'E':
        return t('field_evidence.compass_e', { defaultValue: 'E' });
      case 'SE':
        return t('field_evidence.compass_se', { defaultValue: 'SE' });
      case 'S':
        return t('field_evidence.compass_s', { defaultValue: 'S' });
      case 'SW':
        return t('field_evidence.compass_sw', { defaultValue: 'SW' });
      case 'W':
        return t('field_evidence.compass_w', { defaultValue: 'W' });
      default:
        return t('field_evidence.compass_nw', { defaultValue: 'NW' });
    }
  };
  return (
    <dl className={clsx('space-y-1 text-xs text-content-secondary', className)} data-testid="evidence-details">
      <div className="flex items-center gap-1.5 font-medium">
        {full ? (
          <ShieldCheck size={13} className="text-emerald-600" />
        ) : (
          <ShieldAlert size={13} className="text-amber-500" />
        )}
        <span>{gradeLabel}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <MapPin size={12} className="shrink-0" />
        {loc ? (
          <span>
            {fmtNumber(loc.lat, 6)}, {fmtNumber(loc.lon, 6)}
            {loc.accuracy_m != null &&
              ` ${t('field_evidence.accuracy_short', { defaultValue: '±{{meters}} m', meters: fmtNumber(loc.accuracy_m, 0) })}`}
            {' · '}
            {sourceLabel(loc.source)}
          </span>
        ) : (
          <span>{t('field_evidence.no_location', { defaultValue: 'No location recorded' })}</span>
        )}
      </div>
      {evidence.captured_at && (
        <div className="flex items-center gap-1.5">
          <Clock size={12} className="shrink-0" />
          <span>
            {fmtDate(evidence.captured_at.value, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
            {' · '}
            {sourceLabel(evidence.captured_at.source)}
          </span>
        </div>
      )}
      {typeof heading === 'number' && (
        <div className="flex items-center gap-1.5">
          <Compass size={12} className="shrink-0" />
          <span>
            {t('field_evidence.heading', {
              defaultValue: 'Facing {{point}} ({{degrees}}°)',
              point: compassLabel(compassPoint(heading)),
              degrees: fmtNumber(heading, 0),
            })}
          </span>
        </div>
      )}
      <div className="flex items-center gap-1.5 font-mono text-[10px]" title={evidence.sha256}>
        <Fingerprint size={12} className="shrink-0" />
        <span>SHA-256 {evidence.sha256.slice(0, 16)}</span>
      </div>
    </dl>
  );
}
