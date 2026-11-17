// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where most people meet a seal: the estimate editor, the contract drawer and
 * the variation bill. Each entry renders nothing unless the project's market
 * profile seals estimates and the module answers.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Lock, Plus } from 'lucide-react';
import { Badge, Button, Card, DateDisplay } from '@/shared/ui';
import { archiveApi, shortHash, type SealSummary, type SealedPosition } from './api';
import { PricingDrawer } from './PricingDrawer';
import { SealModal } from './SealModal';
import { receiptVariant } from './labels';

/** Policy and live seals of a project; `enabled` is false until the market says yes. */
function useProjectSeals(projectId: string | undefined) {
  const policy = useQuery({
    queryKey: ['estimate-archive', 'policy', projectId],
    queryFn: () => archiveApi.policy(projectId!),
    enabled: !!projectId,
    retry: false,
    staleTime: 60_000,
  });
  const enabled = !!policy.data?.enabled;
  const seals = useQuery({
    queryKey: ['estimate-archive', 'seals', projectId],
    queryFn: () => archiveApi.seals(projectId),
    enabled: enabled,
    retry: false,
  });
  const live = (seals.data ?? []).filter((s) => s.status !== 'superseded');
  return { enabled, live };
}

const newest = (rows: SealSummary[]) =>
  [...rows].sort((a, b) => b.sealed_at.localeCompare(a.sealed_at))[0];

/** Estimate editor header: a quiet "Sealed" badge, or the action on a locked estimate. */
export function SealAsBasisAction({ projectId, boqId, locked }: { projectId: string; boqId: string; locked: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { enabled, live } = useProjectSeals(projectId);
  const [open, setOpen] = useState(false);
  if (!enabled) return null;
  const seal = newest(live.filter((s) => s.source_boq_id === boqId));
  if (seal) {
    return (
      <Link
        to={`/estimate-archive/${seal.id}`}
        className="inline-flex items-center gap-1 self-center text-xs text-content-secondary hover:text-content-primary"
      >
        <Lock size={12} aria-hidden />
        {t('estimate_archive.entry.sealed_badge', { defaultValue: 'Sealed' })}{' '}
        <DateDisplay value={seal.sealed_at} />
      </Link>
    );
  }
  if (!locked) return null;
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Lock size={14} className="mr-1" />
        {t('estimate_archive.seal_as_basis', { defaultValue: 'Seal as contract basis' })}
      </Button>
      {open && (
        <SealModal
          projectId={projectId}
          boqId={boqId}
          onClose={() => setOpen(false)}
          onSealed={(id) => navigate(`/estimate-archive/${id}`)}
        />
      )}
    </>
  );
}

/** Contract drawer: the contract's seal at a glance, or one line to make it. */
export function ContractSealCard({ projectId, contractId }: { projectId: string; contractId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { enabled, live } = useProjectSeals(projectId);
  const [open, setOpen] = useState(false);
  if (!enabled) return null;
  const seal = newest(live.filter((s) => s.contract_id === contractId));
  return (
    <Card padding="sm">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
        {t('estimate_archive.entry.contract_card', { defaultValue: 'Sealed estimate' })}
      </p>
      {seal ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <Link to={`/estimate-archive/${seal.id}`} className="font-medium text-content-primary hover:underline">
            {seal.label}
          </Link>
          <bdi dir="ltr" className="font-mono text-xs text-content-secondary">
            {shortHash(seal.content_hash)}
          </bdi>
          <Badge variant={receiptVariant(seal.receipt_status)} size="sm">
            {t(`estimate_archive.receipt.${seal.receipt_status}`, { defaultValue: seal.receipt_status })}
          </Badge>
          <span className="text-xs text-content-secondary">
            {t('estimate_archive.entry.openings_count', { defaultValue: 'Openings: {{count}}', count: seal.openings })}
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-sm text-content-secondary">
          <span>{t('estimate_archive.entry.no_seal', { defaultValue: 'No sealed estimate.' })}</span>
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
            {t('estimate_archive.entry.seal_award', { defaultValue: 'Seal the award estimate' })}
          </Button>
        </div>
      )}
      {open && (
        <SealModal
          projectId={projectId}
          contractId={contractId}
          onClose={() => setOpen(false)}
          onSealed={(id) => navigate(`/estimate-archive/${id}`)}
        />
      )}
    </Card>
  );
}

/**
 * Variation bill: price lines from the project's live seal into this bill, and
 * flag lines that claim the original basis with no live seal behind them.
 */
export function VariationSealPricing({
  projectId,
  variationRequestId,
  editable,
  currency,
}: {
  projectId: string;
  variationRequestId: string;
  editable: boolean;
  currency: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { enabled, live } = useProjectSeals(projectId);
  const [picking, setPicking] = useState(false);
  const [position, setPosition] = useState<SealedPosition | null>(null);
  const seal = newest(live);
  const findings = useQuery({
    queryKey: ['estimate-archive', 'variation-findings', variationRequestId],
    queryFn: () => archiveApi.variationFindings(variationRequestId),
    enabled,
    retry: false,
  });
  const contents = useQuery({
    queryKey: ['estimate-archive', 'contents', seal?.id],
    queryFn: () => archiveApi.contents(seal!.id),
    enabled: picking && !!seal,
    retry: false,
  });
  if (!enabled) return null;
  const warnings = findings.data ?? [];
  if (!seal && !warnings.length) return null;
  const scope = contents.data?.scope_ordinals;
  const positions = (contents.data?.payload.positions ?? []).filter(
    (p) => p.resources.length > 0 && (!scope || scope.includes(p.ordinal)),
  );

  return (
    <div className="space-y-2" data-testid="variation-seal-pricing">
      {warnings.map((f, i) => (
        <p key={`${f.code}-${i}`} className="flex items-start gap-1.5 text-xs text-semantic-warning">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
          {f.message}
        </p>
      ))}
      {seal && editable && !picking && (
        <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setPicking(true)}>
          {t('estimate_archive.entry.add_from_seal', { defaultValue: 'Add from sealed estimate' })}
        </Button>
      )}
      {picking && seal && (
        <div className="rounded-lg border border-border-light p-2 text-sm">
          {contents.isError ? (
            <p className="text-xs text-content-secondary">
              {t('estimate_archive.contents_locked', {
                defaultValue: 'The contents stay sealed until a formal opening starts.',
              })}
            </p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {positions.map((p) => (
                <li key={p.ordinal}>
                  <button
                    type="button"
                    className="flex w-full items-baseline gap-2 rounded px-2 py-1 text-start hover:bg-surface-secondary"
                    onClick={() => setPosition(p)}
                  >
                    <bdi dir="ltr" className="font-mono text-xs text-content-tertiary">{p.ordinal}</bdi>
                    <span>{p.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" size="sm" className="mt-1" onClick={() => setPicking(false)}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      )}
      {position && seal && (
        <PricingDrawer
          sealId={seal.id}
          position={position}
          currency={seal.currency || currency}
          variationRequestId={variationRequestId}
          onRecorded={() => {
            setPicking(false);
            void qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes('variation') });
          }}
          onClose={() => setPosition(null)}
        />
      )}
    </div>
  );
}
