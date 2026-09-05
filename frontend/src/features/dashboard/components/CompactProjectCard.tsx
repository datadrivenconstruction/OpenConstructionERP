// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { formatDistanceToNowStrict, isValid as isValidDate, parseISO } from 'date-fns';
import {
  ArrowRight,
  Building2,
  DollarSign,
  Euro,
  PoundSterling,
  Globe2,
  Layers,
} from 'lucide-react';
import { Card } from '@/shared/ui';
import { fmtCompact, fmtNumber, getIntlLocale } from '@/shared/lib/formatters';
import { getDateFnsLocale } from '@/shared/lib/dateFnsLocale';

export interface CompactProjectCardProps {
  id: string;
  name: string;
  description?: string;
  region?: string;
  currency?: string;
  classificationStandard?: string;
  status?: string;
  boqCount?: number;
  boqTotalValue?: number | string | null;
  updatedAt?: string | null;
  createdAt?: string | null;
  style?: React.CSSProperties;
}

const regionColorMap: Record<string, string> = {
  DACH: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  UK: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  US: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  GULF: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  RU: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  NORDIC: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  DEFAULT: 'bg-gray-100 text-gray-700 dark:bg-gray-900/40 dark:text-gray-300',
};

// One of three places that turn a stored classification standard into a name
// for a reader. All three held the same three entries while the picker on
// CreateProjectPage could write eighteen, so every project on a standard
// outside the legacy trio showed its raw identifier on the card. The fallback
// below keeps that from being blank, which is why nobody noticed.
const standardLabels: Record<string, string> = {
  din276: 'DIN 276',
  nrm: 'NRM',
  masterformat: 'MasterFormat',
  uniformat: 'UniFormat',
  uniclass: 'Uniclass',
  omniclass: 'OmniClass',
  gb50500: 'GB/T',
  tetelrend: 'Tételrend',
  gesn: 'GESN / FER',
  bc3: 'BC3',
  untec: 'UNTEC',
  voci: 'VOCI',
  onorm: 'ÖNORM',
  gaeb: 'GAEB',
  sinapi: 'SINAPI',
  sekisan: 'Sekisan',
  kbim: 'KBIM',
  birimfiyat: 'Birim Fiyat',
};

function getRegionAvatarClass(region?: string): string {
  if (region && regionColorMap[region]) return regionColorMap[region];
  return 'bg-oe-blue-subtle text-oe-blue-text';
}

function formatCompactValue(raw: number | string | null | undefined): string {
  const value = typeof raw === 'number' ? raw : Number(raw ?? 0);
  if (!Number.isFinite(value)) return '0';
  // Both branches read the locale per call. The small-value branch used to
  // hold an Intl.NumberFormat built at module scope, which froze the
  // language at whatever the app started in - the comment here described
  // that and left it, so the two branches of one tile disagreed after a
  // language switch.
  if (Math.abs(value) >= 1_000) return fmtCompact(value);
  return fmtNumber(value, 0);
}

export function CompactProjectCard({
  id,
  name,
  description,
  region,
  currency,
  classificationStandard,
  status,
  boqCount,
  boqTotalValue,
  updatedAt,
  createdAt,
  style,
}: CompactProjectCardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const CurrencyIcon =
    currency === 'EUR' ? Euro : currency === 'GBP' ? PoundSterling : DollarSign;

  const modifiedSource = updatedAt || createdAt;
  const modifiedDate = modifiedSource ? parseISO(modifiedSource) : null;
  const relativeModified =
    modifiedDate && isValidDate(modifiedDate)
      ? formatDistanceToNowStrict(modifiedDate, {
          addSuffix: true,
          // Without `locale` date-fns answers in en-US, so this line stayed
          // "3 hours ago" next to an absolute date that was already localised.
          locale: getDateFnsLocale(),
        })
      : null;
  const absoluteModified =
    modifiedDate && isValidDate(modifiedDate)
      ? modifiedDate.toLocaleDateString(getIntlLocale())
      : '';

  const hasValue = typeof boqTotalValue === 'number' && boqTotalValue > 0;

  return (
    <Card
      hoverable
      padding="none"
      className="group cursor-pointer relative animate-card-in overflow-hidden rounded-xl bg-gradient-to-b from-surface-elevated to-surface-primary hover:shadow-lg hover:border-oe-blue/40 focus-within:ring-2 focus-within:ring-oe-blue/30 motion-safe:transition-all"
      style={style}
      onClick={() => navigate(`/projects/${id}`)}
    >
      <div className="p-3.5">
        <div className="flex items-start justify-between gap-2">
          <div
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-bold ring-1 ring-inset ring-white/40 dark:ring-white/5 shadow-sm transition-transform duration-normal ease-oe group-hover:scale-105 ${getRegionAvatarClass(region)}`}
          >
            {name.charAt(0).toUpperCase()}
          </div>
          {status === 'archived' && (
            <span className="inline-flex items-center rounded-md bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-tertiary">
              {t('projects.status_archived', { defaultValue: 'Archived' })}
            </span>
          )}
        </div>

        <h3 className="mt-2.5 text-sm font-semibold tracking-tight text-content-primary truncate">
          {name}
        </h3>
        {description && (
          /* Bumped from text-2xs to text-xs for legibility (audit 2026-05-11). */
          <p className="mt-1 text-xs leading-snug text-content-secondary line-clamp-1">
            {description}
          </p>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-1">
          {classificationStandard && (
            <span className="inline-flex items-center gap-1 rounded-full border border-oe-blue/20 bg-oe-blue-subtle px-1.5 py-0.5 text-2xs font-medium text-oe-blue-text">
              <Building2 size={10} strokeWidth={2.25} />
              {standardLabels[classificationStandard] ?? classificationStandard}
            </span>
          )}
          {currency && (
            <span className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
              <CurrencyIcon size={10} strokeWidth={2.25} />
              {currency}
            </span>
          )}
          {region && (
            <span className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
              <Globe2 size={10} strokeWidth={2.25} />
              {region}
            </span>
          )}
        </div>
      </div>

      {hasValue && (
        <div className="px-3.5 pb-2">
          <div className="rounded-lg border border-border-light bg-gradient-to-br from-oe-blue-subtle/60 via-surface-elevated to-surface-elevated px-3 py-1.5">
            <div className="text-[10px] font-medium uppercase tracking-wider text-content-tertiary">
              {t('projects.card_total_value', { defaultValue: 'Total value' })}
            </div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span className="text-base font-bold tabular-nums text-content-primary">
                {formatCompactValue(boqTotalValue!)}
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                {currency}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-border-light px-3.5 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
            {relativeModified && (
              <span
                className="text-2xs text-content-tertiary truncate"
                title={absoluteModified}
              >
                {relativeModified}
              </span>
            )}
            {typeof boqCount === 'number' && boqCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
                <Layers size={10} strokeWidth={2.25} />
                <span className="tabular-nums">{boqCount}</span>
                <span>{t('projects.boq_short', { defaultValue: 'BOQs' })}</span>
              </span>
            )}
          </div>
          <ArrowRight
            size={12}
            className="shrink-0 text-content-tertiary transition-transform duration-normal ease-oe group-hover:translate-x-0.5 group-hover:text-oe-blue"
          />
        </div>
      </div>
    </Card>
  );
}
