// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Choosing the catalogue of delivery forms a project works from: the first
// step on an empty project, and later the dialog that moves the project to
// another catalogue. A catalogue brings the forms that can be compared, the
// parties, the risk categories and the comparison criteria.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';

import { canManage, type Verdict, type Viewer } from './access';
import {
  changeCatalogue,
  deliveryViolations,
  setModel,
  type CatalogueSummary,
  type DeliveryCatalogue,
  type DeliveryModel,
  type Finding,
} from './api';
import { FindingList, INPUT_CLASS, ReasonedButton, ReviewMark, ServerRefusal } from './DeliveryBits';
import { useDeliveryCatalogues, useRefusalText } from './hooks';
import { catalogueText, formName, type LabelContext } from './labels';

const idOf = (c: Pick<CatalogueSummary, 'source' | 'id'>) => `${c.source}:${c.id}`;

function CatalogueChoice({
  catalogues,
  selected,
  onSelect,
  labels,
  disabled,
  name,
}: {
  catalogues: CatalogueSummary[];
  selected: string;
  onSelect: (id: string) => void;
  labels: LabelContext;
  disabled?: boolean;
  name: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2" role="radiogroup" data-testid="catalogue-choice">
      {catalogues.map((c) => (
        <label
          key={idOf(c)}
          className="flex cursor-pointer items-start gap-3 rounded-lg border border-border-light p-3 text-sm has-[:checked]:border-oe-blue has-[:checked]:bg-oe-blue-subtle"
        >
          <input
            type="radio"
            name={name}
            className="mt-1"
            checked={selected === idOf(c)}
            onChange={() => onSelect(idOf(c))}
            disabled={disabled}
          />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2 font-medium text-content-primary">
              {catalogueText(labels, { key: c.name?.key, texts: c.name?.text, code: c.code })}
              <ReviewMark status={c.review_status} />
            </span>
            <span className="block text-xs text-content-tertiary">
              {c.source === 'tenant'
                ? t('delivery_model.ui.catalogue.source_tenant', { defaultValue: 'Your organisation' })
                : t('delivery_model.ui.catalogue.source_shipped', { defaultValue: 'Shipped with the platform' })}
              {c.latest_version != null && (
                <span className="ml-2">
                  {t('delivery_model.ui.catalogue.version', { defaultValue: 'Version {{version}}', version: c.latest_version })}
                </span>
              )}
            </span>
          </span>
        </label>
      ))}
    </div>
  );
}

export interface StartModelProps {
  projectId: string;
  viewer: Viewer;
  labels: LabelContext;
  onDone: () => void;
}

/** The first step on a project without a delivery model: pick a catalogue and start. */
export function StartModel({ projectId, viewer, labels, onDone }: StartModelProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const cataloguesQ = useDeliveryCatalogues();
  const catalogues = cataloguesQ.data ?? [];
  // Until the reader picks one, the first catalogue is the choice the screen shows and sends.
  const [picked, setPicked] = useState('');
  const chosen = catalogues.find((c) => idOf(c) === picked) ?? catalogues[0];
  const selected = chosen ? idOf(chosen) : '';
  const verdict: Verdict = canManage(viewer);

  const start = useMutation({
    mutationFn: (pick: CatalogueSummary | undefined) =>
      setModel(projectId, pick ? { catalogue_source: pick.source, catalogue_id: pick.id } : {}),
    onSuccess: onDone,
  });

  if (cataloguesQ.isLoading) return <SkeletonTable rows={2} columns={2} />;
  if (cataloguesQ.isError) {
    return (
      <ErrorState
        title={t('delivery_model.ui.catalogue.load_failed', { defaultValue: 'The catalogues of delivery forms could not be loaded' })}
        hint={getErrorMessage(cataloguesQ.error)}
        onRetry={() => cataloguesQ.refetch()}
      />
    );
  }

  return (
    <section className="space-y-3 rounded-xl border border-border bg-surface-elevated shadow-sm p-4" data-testid="start-model">
      <div>
        <h2 className="text-sm font-semibold text-content-primary">
          {t('delivery_model.ui.start.heading', { defaultValue: 'Catalogue of delivery forms' })}
        </h2>
        <p className="text-xs text-content-secondary">
          {t('delivery_model.ui.start.body', {
            defaultValue: 'It brings the forms you can compare, the comparison criteria and the usual split of risks for each form.',
          })}
        </p>
      </div>
      {catalogues.length === 0 ? (
        <p className="text-sm text-content-secondary" data-testid="no-catalogues">
          {t('delivery_model.ui.catalogue.none', { defaultValue: 'No catalogue of delivery forms is published yet.' })}
        </p>
      ) : (
        <CatalogueChoice
          catalogues={catalogues}
          selected={selected}
          onSelect={setPicked}
          labels={labels}
          disabled={!!verdict}
          name="delivery-catalogue"
        />
      )}
      <ServerRefusal message={start.isError ? refusal(start.error) : null} />
      <ReasonedButton
        verdict={verdict}
        loading={start.isPending}
        disabled={catalogues.length === 0}
        onClick={() => start.mutate(chosen)}
        data-testid="start-model-button"
      >
        {t('delivery_model.ui.start.action', { defaultValue: 'Start delivery model' })}
      </ReasonedButton>
    </section>
  );
}

export interface ChangeCatalogueDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  model: DeliveryModel;
  /** The pinned catalogue, used to name the forms that need a match. */
  pinned: DeliveryCatalogue | null;
  labels: LabelContext;
  onDone: () => void;
}

/**
 * Moving the project to another catalogue. Forms and risk categories with the
 * same code carry over. When a compared form has no namesake the server lists
 * it, and the dialog then asks for the code of the form that replaces it.
 */
export function ChangeCatalogueDialog({ open, onClose, projectId, model, pinned, labels, onDone }: ChangeCatalogueDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const cataloguesQ = useDeliveryCatalogues(open);
  const catalogues = cataloguesQ.data ?? [];
  const [selected, setSelected] = useState(`${model.catalogue_source}:${model.catalogue_id}`);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [violations, setViolations] = useState<Finding[]>([]);

  const change = useMutation({
    mutationFn: () => {
      const chosen = catalogues.find((c) => idOf(c) === selected);
      if (!chosen) throw new Error('no catalogue selected');
      const formMapping: Record<string, string> = {};
      for (const [from, to] of Object.entries(mapping)) if (to.trim()) formMapping[from] = to.trim();
      return changeCatalogue(projectId, {
        catalogue_source: chosen.source,
        catalogue_id: chosen.id,
        form_mapping: formMapping,
        category_mapping: {},
      });
    },
    onSuccess: () => {
      setViolations([]);
      setMapping({});
      onDone();
      onClose();
    },
    onError: (err) => setViolations(deliveryViolations(err)),
  });

  const unmapped = [...new Set(violations.filter((v) => v.code.startsWith('form_mapping')).map((v) => v.ref))];
  const nameOfForm = (code: string) => formName(labels, pinned?.forms.find((f) => f.code === code) ?? null, code);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={change.isPending}
      testId="change-catalogue-dialog"
      title={t('delivery_model.ui.catalogue.change_title', { defaultValue: 'Use another catalogue' })}
      subtitle={t('delivery_model.ui.catalogue.change_subtitle', {
        defaultValue: 'Forms and risk categories with the same code carry over. Risk allocations that find no match go back to unconfirmed.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={change.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={change.isPending} disabled={!catalogues.some((c) => idOf(c) === selected)} onClick={() => change.mutate()} data-testid="change-catalogue-send">
            {t('delivery_model.ui.catalogue.change_send', { defaultValue: 'Use this catalogue' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <ServerRefusal message={change.isError ? refusal(change.error) : null} />
        {cataloguesQ.isLoading ? (
          <SkeletonTable rows={2} columns={2} />
        ) : (
          <CatalogueChoice catalogues={catalogues} selected={selected} onSelect={setSelected} labels={labels} name="delivery-catalogue-change" />
        )}
        {unmapped.length > 0 && (
          <div className="space-y-2" data-testid="form-mapping">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('delivery_model.ui.catalogue.mapping_heading', { defaultValue: 'Forms that need a match' })}
            </h3>
            <p className="text-xs text-content-secondary">
              {t('delivery_model.ui.catalogue.mapping_body', {
                defaultValue: 'These compared forms are not in the new catalogue. Enter the code of the form that replaces each one.',
              })}
            </p>
            {unmapped.map((code) => (
              <label key={code} className="flex items-center gap-3 text-sm">
                <span className="w-1/2 truncate">{nameOfForm(code)}</span>
                <input
                  className={INPUT_CLASS}
                  value={mapping[code] ?? ''}
                  onChange={(e) => setMapping((m) => ({ ...m, [code]: e.target.value }))}
                  aria-label={t('delivery_model.ui.catalogue.mapping_field', {
                    defaultValue: 'Code of the form that replaces {{form}}',
                    form: nameOfForm(code),
                  })}
                />
              </label>
            ))}
            <FindingList findings={violations.filter((v) => v.code !== 'form_mapping_missing')} refName={nameOfForm} />
          </div>
        )}
      </div>
    </WideModal>
  );
}
