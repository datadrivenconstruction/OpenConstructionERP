// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Starting or changing the concept: which rule catalogue applies, under which
// procurement law, for what kind of client, and which gate releases
// procurement. The laws and the kinds of client are the catalogue's own, so
// the form offers what the chosen catalogue brings, never a fixed list.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import { setConcept, type CatalogueSummary, type Concept } from './api';
import { useGates } from './hooks';
import { gateName, CLIENT_TYPE, JURISDICTION, catalogueName, errorText, vocab, type LabelContext } from './labels';
import { FIELD_CLASS, Field, ProblemList, RefusalBox } from './ProcurementBits';
import { conceptInput, gateVerdict, parseAmount, publicClientTypes } from './rules';

function catalogueLabel(labels: LabelContext, c: CatalogueSummary): string {
  if (c.name.key && labels.exists(c.name.key)) return labels.t(c.name.key);
  const lang = labels.language.split('-')[0] ?? 'en';
  return c.name.text?.[labels.language] ?? c.name.text?.[lang] ?? c.name.text?.en ?? c.code;
}

export interface ConceptDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Null when the project has no concept yet. */
  concept: Concept | null;
  catalogues: CatalogueSummary[];
  /** The catalogue list is still on its way. */
  cataloguesLoading?: boolean;
  labels: LabelContext;
  onSaved: () => void;
}

export function ConceptDialog({ open, onClose, projectId, concept, catalogues, cataloguesLoading = false, labels, onSaved }: ConceptDialogProps) {
  const { t } = useTranslation();
  const pinned = concept ? `${concept.catalogue_source}:${concept.catalogue_id}` : null;
  const [picked, setPicked] = useState<string | null>(pinned);
  // A catalogue without laws has no published version and cannot be pinned.
  const usable = catalogues.filter((c) => (c.jurisdictions ?? []).length > 0 || `${c.source}:${c.id}` === pinned);
  // Until the reader picks one, a new concept shows the first catalogue the server lists.
  const catalogue = picked ?? (usable[0] ? `${usable[0].source}:${usable[0].id}` : '');
  const listed = usable.find((c) => `${c.source}:${c.id}` === catalogue);
  // The laws of the chosen catalogue; for the pinned one the concept carries them too.
  const laws = listed?.jurisdictions?.length ? listed.jurisdictions : catalogue === pinned ? (concept?.jurisdictions ?? []) : [];

  const [lawPick, setLawPick] = useState(concept?.jurisdiction ?? '');
  const [publicClient, setPublicClient] = useState(concept?.public_client ?? false);
  const [clientType, setClientType] = useState(concept?.client_type ?? '');
  const [vat, setVat] = useState(concept?.vat_rate_pct ?? '0');
  const [gate, setGate] = useState(concept?.release_gate_code ?? '');

  // A choice made under another catalogue falls back to the first law this one knows.
  const law = laws.find((j) => j.code === lawPick) ?? laws[0];
  const publicTypes = publicClientTypes(law);
  const isPublic = publicClient && publicTypes.length > 0;
  const chosenType = publicTypes.includes(clientType) ? clientType : (publicTypes[0] ?? '');
  const vatAmount = parseAmount(vat || '0');
  const vatBad = vatAmount === null || Number(vatAmount) > 100;

  // The gate is named on an existing concept only: who may name it is the server's call, sent with the concept.
  const gateOff = concept ? gateVerdict(concept) : null;
  // The server's answer: the project never adopted a phase model, so there is no gate to name.
  const gatesUnused = concept?.gates_in_use === false;
  const gatesQ = useGates(projectId, open && !!concept && !gatesUnused);
  const gates = gatesQ.data ?? [];
  const tagged = gates.find((g) => g.tagged_release_gate);
  // The server's answer: the phase model opens procurement in its first phase, so no gate releases it.
  const fromStart = concept?.released_from_start === true;

  const save = useMutation({
    mutationFn: () =>
      setConcept(
        projectId,
        conceptInput(concept, {
          catalogue,
          jurisdiction: law?.code ?? '',
          public_client: isPublic,
          client_type: chosenType,
          vat_rate_pct: vatAmount ?? '0',
          release_gate_code: !concept || gateOff ? null : gate,
        }),
      ),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="concept-dialog"
      title={
        concept
          ? t('procurement_concept.ui.concept.edit_title', { defaultValue: 'Procurement rules of this project' })
          : t('procurement_concept.ui.concept.start_title', { defaultValue: 'Start the procurement concept' })
      }
      subtitle={t('procurement_concept.ui.concept.dialog_subtitle', {
        defaultValue:
          'These answers decide which thresholds are tested and which procedures the packages may use.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList
            problems={
              vatBad
                ? [['procurement_concept.ui.problem.vat_invalid', 'The VAT rate is a number from 0 to 100.']]
                : []
            }
          />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={vatBad || !law} onClick={() => save.mutate()} data-testid="concept-save">
            {concept
              ? t('procurement_concept.ui.save', { defaultValue: 'Save' })
              : t('procurement_concept.ui.concept.start', { defaultValue: 'Start concept' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        {cataloguesLoading && (
          <p className="text-sm text-content-tertiary" data-testid="catalogues-loading">
            {t('procurement_concept.ui.concept.catalogues_loading', { defaultValue: 'Reading the rule catalogues' })}
          </p>
        )}
        {!cataloguesLoading && usable.length === 0 && (
          <p className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary" role="note" data-testid="catalogues-none">
            {t('procurement_concept.ui.concept.catalogues_none', {
              defaultValue:
                'No rule catalogue can be used yet, so the concept cannot be started. A catalogue needs a published version with at least one procurement law. Ask the person who manages the catalogues of your company to publish one.',
            })}
          </p>
        )}
        <Field
          label={t('procurement_concept.ui.concept.catalogue', { defaultValue: 'Rule catalogue' })}
          htmlFor="pc-catalogue"
          hint={t('procurement_concept.ui.concept.catalogue_hint', {
            defaultValue: 'The catalogue brings the procedures, the thresholds with their sources and the usual lead times.',
          })}
        >
          <select id="pc-catalogue" className={FIELD_CLASS} value={catalogue} onChange={(e) => setPicked(e.target.value)}>
            {pinned && concept && !listed && catalogue === pinned && <option value={pinned}>{concept.catalogue_id}</option>}
            {usable.map((c) => (
              <option key={`${c.source}:${c.id}`} value={`${c.source}:${c.id}`}>
                {catalogueLabel(labels, c)}
              </option>
            ))}
          </select>
        </Field>

        <Field label={t('procurement_concept.ui.concept.jurisdiction', { defaultValue: 'Procurement law' })} htmlFor="pc-jurisdiction">
          <select id="pc-jurisdiction" className={FIELD_CLASS} value={law?.code ?? ''} onChange={(e) => setLawPick(e.target.value)}>
            {laws.map((j) => (
              <option key={j.code} value={j.code}>
                {catalogueName(labels, 'jurisdiction', j) || vocab(labels.t, JURISDICTION, j.code)}
              </option>
            ))}
          </select>
        </Field>

        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="mt-1"
            checked={isPublic}
            disabled={publicTypes.length === 0}
            onChange={(e) => setPublicClient(e.target.checked)}
            data-testid="concept-public-client"
          />
          <span>
            {t('procurement_concept.ui.concept.public_client', { defaultValue: 'The client is a public body' })}
            <span className="block text-xs text-content-tertiary">
              {publicTypes.length === 0
                ? t('procurement_concept.ui.concept.no_public_types', {
                    defaultValue: 'This law knows no public client, so no threshold applies.',
                  })
                : t('procurement_concept.ui.concept.public_client_hint', {
                    defaultValue: 'Thresholds apply to public clients only. A private client keeps the law for reference.',
                  })}
            </span>
          </span>
        </label>

        {isPublic && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('procurement_concept.ui.concept.client_type', { defaultValue: 'Kind of public client' })} htmlFor="pc-client-type">
              <select id="pc-client-type" className={FIELD_CLASS} value={chosenType} onChange={(e) => setClientType(e.target.value)}>
                {publicTypes.map((c) => (
                  <option key={c} value={c}>
                    {vocab(labels.t, CLIENT_TYPE, c)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('procurement_concept.ui.concept.vat', { defaultValue: 'VAT rate in percent' })}
              htmlFor="pc-vat"
              hint={t('procurement_concept.ui.concept.vat_hint', {
                defaultValue: 'Used when a threshold is stated on the other VAT basis than the estimate.',
              })}
            >
              <input id="pc-vat" inputMode="decimal" className={FIELD_CLASS} value={vat} onChange={(e) => setVat(e.target.value)} />
            </Field>
          </div>
        )}

        {concept && gatesUnused && (
          <div className="text-sm" role="note" data-testid="gates-not-used">
            <p className="font-medium text-content-primary">
              {t('procurement_concept.ui.concept.release_gate', { defaultValue: 'Gate that releases procurement' })}
            </p>
            <p className="mt-1 text-content-secondary">
              {t('procurement_concept.ui.concept.gates_not_used', {
                defaultValue: 'This project does not use gates, so no gate releases procurement. A gate can be named here once the project has a phase model.',
              })}
            </p>
          </div>
        )}
        {concept && !gatesUnused && (
          <Field
            label={t('procurement_concept.ui.concept.release_gate', { defaultValue: 'Gate that releases procurement' })}
            htmlFor="pc-gate"
            hint={
              gateOff
                ? errorText(labels.t, gateOff)
                : fromStart
                  ? t('procurement_concept.ui.concept.released_from_start_hint', {
                      defaultValue:
                        'The phase model of this project opens procurement in its first phase. Name a gate only if procurement should wait for it.',
                    })
                  : t('procurement_concept.ui.concept.release_gate_hint', {
                      defaultValue: 'Main works may go to tender once this gate is decided. Advance packages need their own release.',
                    })
            }
          >
            <select id="pc-gate" className={FIELD_CLASS} disabled={!!gateOff} value={gate} onChange={(e) => setGate(e.target.value)}>
              <option value="">
                {fromStart
                  ? t('procurement_concept.ui.concept.gate_none_from_start', {
                      defaultValue: 'No gate, procurement is open from the project start',
                    })
                  : tagged
                  ? t('procurement_concept.ui.concept.gate_tagged', {
                      defaultValue: 'The gate the governance plan names ({{code}})',
                      code: tagged.code,
                    })
                  : t('procurement_concept.ui.concept.gate_default', { defaultValue: 'The gate the governance plan names' })}
              </option>
              {gate && !gates.some((g) => g.code === gate) && <option value={gate}>{gate}</option>}
              {gates.map((g) => (
                <option key={g.code} value={g.code}>
                  {gateName(labels, g)}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
    </WideModal>
  );
}
