// Design module (ERP side of the design editor link).
/**
 * Headline figures above the overview steps: current revision, estimate (compact; the estimate page has the
 * exact figures), priced positions, linked elements. Counts and server figures only; a tile without data says so instead of a zero.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Boxes, Calculator, Link2, ListChecks } from 'lucide-react';
import { KpiBand, type KpiBandItem } from '@/shared/ui';
import { fetchAccess, fetchEstimate } from './api';
import { tr } from './BriefFields';
import type { OverviewStep, StepId } from './linksApi';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { moneyWhole } from './money';

/** 4782640 -> "4,8 Mio. €": fits a tile at 1024 px. */
function compact(v: string, currency: string): string {
  const lang = getNumberLocale();
  const n = Number(v);
  if (!Number.isFinite(n)) return '–';
  try {
    return new Intl.NumberFormat(lang, { notation: 'compact', maximumFractionDigits: 1,
      ...(currency ? { style: 'currency', currency } : {}) }).format(n);
  } catch {
    return new Intl.NumberFormat(lang, { notation: 'compact', maximumFractionDigits: 1 }).format(n);
  }
}

export function OverviewKpis({ projectId, steps }: { projectId: string; steps: OverviewStep[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // same keys as the estimate page: one request serves both
  const est = useQuery({ queryKey: ['design-estimate', projectId], queryFn: () => fetchEstimate(projectId) });
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId), retry: false });
  const step = (id: StepId) => steps.find((s) => s.id === id);
  const go = (id: StepId) => { const s = step(id); return s ? () => navigate(s.url) : undefined; };
  const none = tr(t, 'design.overview.kpi.none');

  const model = step('model');
  const e = est.data?.estimate ? est.data : null;
  const currency = e ? (e.range.currency ?? access.data?.currency ?? '') : '';
  const n = e?.positions.length ?? 0;
  const unpriced = e?.unpriced_positions.length ?? 0;

  const items: KpiBandItem[] = [
    {
      key: 'revision', icon: Boxes, label: tr(t, 'design.overview.kpi.revision'), onClick: go('model'),
      value: model?.current ? tr(t, 'design.revisions.number', { number: model.current }) : none,
      sub: model?.waiting ? tr(t, 'design.overview.state.waiting', { count: model.waiting })
        : tr(t, 'design.overview.kpi.revisions', { count: model?.count ?? 0 }),
      tone: model?.waiting ? 'warning' : undefined,
    },
    {
      key: 'estimate', icon: Calculator, label: tr(t, 'design.overview.kpi.estimate'), onClick: go('estimate'),
      value: e ? compact(e.range.total.mid, currency) : est.isLoading ? '…' : none,
      ariaLabel: e ? `${tr(t, 'design.overview.kpi.estimate')}: ${moneyWhole(e.range.total.mid, currency)}` : undefined,
      sub: e ? tr(t, 'design.overview.kpi.range', {
        low: compact(e.range.total.low, currency), high: compact(e.range.total.high, currency) }) : undefined,
    },
    {
      key: 'priced', icon: ListChecks, label: tr(t, 'design.overview.kpi.priced'), onClick: go('estimate'),
      value: e ? `${n - unpriced} / ${n}` : none,
      sub: e && unpriced ? tr(t, 'design.overview.kpi.unpriced', { count: unpriced }) : undefined,
      tone: e && unpriced ? 'warning' : undefined,
    },
    {
      key: 'linked', icon: Link2, label: tr(t, 'design.overview.kpi.linked'), onClick: go('bim'),
      value: step('bim')?.done ? (step('bim')?.count ?? 0).toLocaleString(getNumberLocale()) : none,
    },
  ];
  return <div data-testid="overview-kpis"><KpiBand items={items} /></div>;
}
