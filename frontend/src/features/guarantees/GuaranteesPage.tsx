// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Project register of bank guarantees and bonds. */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Landmark, Plus, BarChart3 } from 'lucide-react';
import { Button, Card, Badge, EmptyState, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import {
  GUARANTEE_DIRECTIONS,
  GUARANTEE_STATUSES,
  GUARANTEE_TYPES,
  createGuarantee,
  useGuaranteeMutation,
  useGuaranteeValidation,
  useGuarantees,
  type GuaranteeCreate,
  type GuaranteeDirection,
  type GuaranteeStatus,
  type GuaranteeType,
} from './api';
import { directionLabel, statusLabel, statusVariant, typeLabel } from './labels';
import { buildGuaranteesInsights } from './guaranteesInsights';
import { guaranteesGuide } from './guaranteesGuide';
import { GuaranteeFormModal } from './GuaranteeFormModal';
import { AlertBadge, GuaranteesExplainer, Money, ValidationBlock, selectCls } from './ui';

export function GuaranteesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const addToast = useToastStore((s) => s.addToast);

  const [typeFilter, setTypeFilter] = useState<GuaranteeType | ''>('');
  const [statusFilter, setStatusFilter] = useState<GuaranteeStatus | ''>('');
  const [directionFilter, setDirectionFilter] = useState<GuaranteeDirection | ''>('');
  const [createOpen, setCreateOpen] = useState(false);

  const filters = useMemo(
    () => ({ guarantee_type: typeFilter, status: statusFilter, direction: directionFilter }),
    [typeFilter, statusFilter, directionFilter],
  );
  const listQ = useGuarantees(projectId, filters);
  // The unfiltered register feeds the insights so the charts do not change with the table filters.
  const allQ = useGuarantees(projectId, {});
  const validationQ = useGuaranteeValidation(projectId);
  const createMut = useGuaranteeMutation((body: GuaranteeCreate) => createGuarantee(projectId, body));

  // Hooks stay above any early return.
  const insights = useModuleInsights('guarantees', { defaultOpen: false });
  const { datasets, builtins } = useMemo(
    () => buildGuaranteesInsights(allQ.data ?? [], t),
    [allQ.data, t],
  );

  const rows = listQ.data ?? [];
  const filtered = !!(typeFilter || statusFilter || directionFilter);

  const handleCreate = (body: GuaranteeCreate) => {
    createMut.mutate(body, {
      onSuccess: (g) => {
        setCreateOpen(false);
        addToast({ type: 'success', title: t('guarantees.created_toast', { defaultValue: 'Guarantee created' }) });
        navigate(`/projects/${projectId}/guarantees/${g.id}`);
      },
      onError: (e) =>
        addToast({ type: 'error', title: t('guarantees.create_failed', { defaultValue: 'Could not create the guarantee' }), message: getErrorMessage(e) }),
    });
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('guarantees.title', { defaultValue: 'Guarantees & Bonds' })}
        subtitle={t('guarantees.subtitle', { defaultValue: 'Bank guarantees and bonds given and received, with expiry alerts and exposure' })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={guaranteesGuide} />
            <Link to="/portfolio/guarantees">
              <Button variant="secondary" size="sm" icon={<BarChart3 size={14} />}>
                {t('guarantees.open_exposure', { defaultValue: 'Exposure' })}
              </Button>
            </Link>
            <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)} disabled={!projectId} icon={<Plus size={14} />}>
              {t('guarantees.new', { defaultValue: 'New guarantee' })}
            </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('guarantees.insights.title', { defaultValue: 'Guarantee insights' })}
        datasets={datasets}
        builtins={builtins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <RequiresProject emptyHint={t('guarantees.select_project', { defaultValue: 'Open a project first to manage its guarantees and bonds.' })}>
        <div className="space-y-5">
          <GuaranteesExplainer />

          {validationQ.data && <ValidationBlock findings={validationQ.data.findings} />}

          <div className="flex flex-wrap items-center gap-2">
            <select aria-label={t('guarantees.field_type', { defaultValue: 'Type' })} className={`${selectCls} !w-auto`} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as GuaranteeType | '')}>
              <option value="">{t('guarantees.filter_all_types', { defaultValue: 'All types' })}</option>
              {GUARANTEE_TYPES.map((v) => (
                <option key={v} value={v}>{typeLabel(t, v)}</option>
              ))}
            </select>
            <select aria-label={t('guarantees.col_status', { defaultValue: 'Status' })} className={`${selectCls} !w-auto`} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as GuaranteeStatus | '')}>
              <option value="">{t('guarantees.filter_all_statuses', { defaultValue: 'All statuses' })}</option>
              {GUARANTEE_STATUSES.map((v) => (
                <option key={v} value={v}>{statusLabel(t, v)}</option>
              ))}
            </select>
            <select aria-label={t('guarantees.field_direction', { defaultValue: 'Direction' })} className={`${selectCls} !w-auto`} value={directionFilter} onChange={(e) => setDirectionFilter(e.target.value as GuaranteeDirection | '')}>
              <option value="">{t('guarantees.filter_all_directions', { defaultValue: 'Given and received' })}</option>
              {GUARANTEE_DIRECTIONS.map((v) => (
                <option key={v} value={v}>{directionLabel(t, v)}</option>
              ))}
            </select>
          </div>

          {listQ.isLoading ? (
            <Card padding="lg" className="text-center text-sm text-content-tertiary">
              {t('guarantees.loading', { defaultValue: 'Loading...' })}
            </Card>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Landmark size={28} strokeWidth={1.5} />}
              title={filtered ? t('guarantees.empty_filtered', { defaultValue: 'No guarantees match this filter' }) : t('guarantees.empty', { defaultValue: 'No guarantees yet' })}
              description={filtered ? undefined : t('guarantees.empty_hint', { defaultValue: 'Register the first bank guarantee or bond for this project.' })}
              action={filtered ? undefined : { label: t('guarantees.new', { defaultValue: 'New guarantee' }), onClick: () => setCreateOpen(true) }}
            />
          ) : (
            <Card padding="none" className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.col_reference', { defaultValue: 'Reference' })}</th>
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.field_type', { defaultValue: 'Type' })}</th>
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.field_issuer_bank', { defaultValue: 'Issuing bank' })}</th>
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.field_beneficiary', { defaultValue: 'Beneficiary' })}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t('guarantees.field_amount', { defaultValue: 'Amount' })}</th>
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.field_expiry_date', { defaultValue: 'Expiry date' })}</th>
                    <th className="px-4 py-2.5 font-medium">{t('guarantees.col_status', { defaultValue: 'Status' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((g) => (
                    <tr
                      key={g.id}
                      onClick={() => navigate(`/projects/${projectId}/guarantees/${g.id}`)}
                      className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary"
                    >
                      <td className="px-4 py-3 font-medium text-content-primary">
                        <Link to={`/projects/${projectId}/guarantees/${g.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                          {g.reference}
                        </Link>
                        <div className="text-2xs font-normal text-content-tertiary">{directionLabel(t, g.direction)}</div>
                      </td>
                      <td className="px-4 py-3 text-content-secondary">{typeLabel(t, g.guarantee_type)}</td>
                      <td className="px-4 py-3 text-content-secondary">{g.issuer_bank || '—'}</td>
                      <td className="px-4 py-3 text-content-secondary">{g.beneficiary || '—'}</td>
                      <td className="px-4 py-3 text-right text-content-primary"><Money value={g.amount} currency={g.currency} /></td>
                      <td className="px-4 py-3 text-content-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                          <DateDisplay value={g.expiry_date} />
                          <AlertBadge band={g.alert_band} days={g.days_to_expiry} />
                        </div>
                      </td>
                      <td className="px-4 py-3"><Badge variant={statusVariant(g.status)}>{statusLabel(t, g.status)}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      </RequiresProject>

      {createOpen && (
        <GuaranteeFormModal projectId={projectId} isPending={createMut.isPending} onClose={() => setCreateOpen(false)} onSubmit={handleCreate} />
      )}
    </div>
  );
}
