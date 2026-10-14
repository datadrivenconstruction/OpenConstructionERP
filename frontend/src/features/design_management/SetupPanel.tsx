// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Design setup: the numbering scheme the project's drawing numbers follow,
// and the switches of the design process. `SetupStart` is what a project
// without a setup sees: one choice and one button. Changing the scheme later
// keeps every existing number; those drawings are marked and can be given new
// numbers from the drawing register.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Settings2 } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  changeScheme,
  createSetup,
  designKeys,
  listSchemes,
  updateSetup,
  type CatalogueSource,
  type CatalogueSummary,
  type Purpose,
  type SetupPatchInput,
} from './api';
import { InlineQueryState, PanelHeader, SUITABILITY_OPTIONS, phaseOptions, roleOptions, roleTitle, type DesignContext, WriteButton } from './DesignBits';
import { FormDialog, flag, str, type FieldSpec, type FormValues } from './FormDialog';
import { refusalText } from './hooks';
import { PURPOSE, fieldLabel, labelOf, phaseName, schemeName, ui, uiCount, vocab, vocabOptions, type LabelContext, type TFn } from './labels';

const TARGET = 'target_';

function useSchemes() {
  return useQuery({ queryKey: designKeys.catalogues('drawing_numbering'), queryFn: listSchemes, staleTime: 300_000 });
}

function schemeChoice(labels: LabelContext, scheme: CatalogueSummary): string {
  return labelOf(labels, scheme.name, scheme.code);
}

/** `source:id`, because a tenant scheme and a shipped one may share an id. */
function choiceValue(scheme: Pick<CatalogueSummary, 'source' | 'id'>): string {
  return `${scheme.source}:${scheme.id}`;
}

function parseChoice(value: string): { source: CatalogueSource; id: string } {
  const at = value.indexOf(':');
  return { source: value.slice(0, at) as CatalogueSource, id: value.slice(at + 1) };
}

export function SetupStart({ projectId, labels, onDone }: { projectId: string; labels: LabelContext; onDone: () => void }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const schemes = useSchemes();
  const [choice, setChoice] = useState('');
  const [fourEyes, setFourEyes] = useState(true);
  const [refusal, setRefusal] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      createSetup(projectId, {
        four_eyes_release: fourEyes,
        ...(choice ? { scheme_source: parseChoice(choice).source, scheme_id: parseChoice(choice).id } : {}),
      }),
    onSuccess: onDone,
    onError: (err) => setRefusal(refusalText(t, err)),
  });
  const usable = (schemes.data ?? []).filter((s) => s.state === 'published' && s.latest_version !== null);

  return (
    <div className="space-y-4" data-testid="design-setup-start">
      <EmptyState icon={<Settings2 size={28} />} title={ui(t, 'design.ui.start.title')} description={ui(t, 'design.ui.start.body')} />
      <InlineQueryState query={schemes} />
      <div className="mx-auto max-w-2xl space-y-3 rounded-lg border border-border-light p-4">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-content-primary">{ui(t, 'design.ui.start.scheme')}</legend>
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input type="radio" name="design-scheme" className="mt-1" checked={choice === ''} onChange={() => setChoice('')} />
            <span>
              {ui(t, 'design.ui.start.scheme_default')}
              <span className="block text-xs text-content-secondary">{ui(t, 'design.ui.start.scheme_default_hint')}</span>
            </span>
          </label>
          {usable.map((scheme) => (
            <label key={choiceValue(scheme)} className="flex items-start gap-2 text-sm text-content-primary" data-testid="scheme-choice">
              <input
                type="radio"
                name="design-scheme"
                className="mt-1"
                checked={choice === choiceValue(scheme)}
                onChange={() => setChoice(choiceValue(scheme))}
              />
              <span>
                {schemeChoice(labels, scheme)}
                {scheme.review_status !== 'verified' && <span className="ml-1 text-xs italic text-content-tertiary">{ui(t, 'design.ui.unconfirmed')}</span>}
              </span>
            </label>
          ))}
        </fieldset>
        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input type="checkbox" className="mt-1 h-4 w-4" checked={fourEyes} onChange={(e) => setFourEyes(e.target.checked)} />
          <span>
            {ui(t, 'design.ui.setup.four_eyes')}
            <span className="block text-xs text-content-secondary">{ui(t, 'design.ui.setup.four_eyes_hint')}</span>
          </span>
        </label>
        {refusal && (
          <p role="alert" className="text-sm text-semantic-error" data-testid="setup-refusal">
            {refusal}
          </p>
        )}
        <WriteButton need="manage" loading={save.isPending} onClick={() => save.mutate()} data-testid="setup-save">
          {ui(t, 'design.ui.start.save')}
        </WriteButton>
      </div>
    </div>
  );
}

export function SetupPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const addToast = useToastStore((s) => s.addToast);
  const [dialog, setDialog] = useState<'settings' | 'scheme' | null>(null);
  const schemes = useSchemes();
  const { setup, labels } = ctx;
  const scheme = setup.scheme;
  const phases = setup.phases;
  const description = scheme.description_key && labels.exists(scheme.description_key) ? labels.t(scheme.description_key) : '';

  const settings: FormValues = {
    four_eyes_release: setup.four_eyes_release,
    default_distribution_purpose: setup.default_distribution_purpose,
    lead_designer_role_id: setup.lead_designer_role_id ?? '',
    hierarchical_codes: setup.hierarchical_codes,
    wbs_separator: setup.wbs_separator,
    ...Object.fromEntries(phases.map((p) => [`${TARGET}${p.code}`, setup.target_suitability[p.code] ?? ''])),
  };
  const settingsFields: FieldSpec[] = [
    { name: 'four_eyes_release', label: ui(t, 'design.ui.setup.four_eyes'), type: 'checkbox', hint: ui(t, 'design.ui.setup.four_eyes_hint') },
    { name: 'default_distribution_purpose', label: ui(t, 'design.ui.setup.default_purpose'), type: 'select', required: true, options: vocabOptions(t, PURPOSE) },
    { name: 'lead_designer_role_id', label: ui(t, 'design.ui.setup.lead_designer'), type: 'select', options: roleOptions(ctx) },
    { name: 'hierarchical_codes', label: ui(t, 'design.ui.setup.hierarchical'), type: 'checkbox', hint: ui(t, 'design.ui.setup.hierarchical_hint') },
    {
      name: 'wbs_separator',
      label: ui(t, 'design.ui.setup.separator'),
      type: 'select',
      required: true,
      options: ['.', '-', '/'].map((s) => ({ value: s, label: s })),
    },
    ...phaseOptions(ctx).map((p) => ({
      name: `${TARGET}${p.value}`,
      label: ui(t, 'design.ui.setup.target_for', { phase: p.label }),
      type: 'select' as const,
      options: SUITABILITY_OPTIONS,
    })),
  ];
  const settingsBody = (values: FormValues): SetupPatchInput => {
    const target: Record<string, string> = {};
    for (const p of phases) {
      const code = str(values, `${TARGET}${p.code}`);
      if (code) target[p.code] = code;
    }
    return {
      four_eyes_release: flag(values, 'four_eyes_release'),
      default_distribution_purpose: str(values, 'default_distribution_purpose') as Purpose,
      lead_designer_role_id: str(values, 'lead_designer_role_id') || null,
      hierarchical_codes: flag(values, 'hierarchical_codes'),
      wbs_separator: str(values, 'wbs_separator'),
      target_suitability: target,
    };
  };

  const others = (schemes.data ?? []).filter(
    (s) => s.state === 'published' && s.latest_version !== null && !(s.source === setup.scheme_source && s.id === setup.scheme_id),
  );
  const targets = phases.filter((p) => setup.target_suitability[p.code]);

  return (
    <div className="space-y-4" data-testid="design-setup-panel">
      <PanelHeader
        title={ui(t, 'design.ui.setup.title')}
        hint={ui(t, 'design.ui.setup.hint')}
        action={
          <WriteButton need="manage" onClick={() => setDialog('settings')} data-testid="setup-edit">
            {ui(t, 'design.ui.setup.edit')}
          </WriteButton>
        }
      />

      <section className="space-y-2 rounded-lg border border-border-light p-4" data-testid="setup-scheme">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.scheme')}</p>
            <h3 className="font-medium text-content-primary">{schemeName(labels, scheme)}</h3>
            {description && <p className="text-sm text-content-secondary">{description}</p>}
            <InlineQueryState query={schemes} />
          </div>
          <WriteButton need="manage" variant="secondary" size="sm" onClick={() => setDialog('scheme')} data-testid="scheme-change">
            {ui(t, 'design.ui.setup.scheme_change')}
          </WriteButton>
        </div>
        <p className="text-sm text-content-secondary">{ui(t, 'design.ui.setup.parts')}</p>
        <ol className="flex flex-wrap items-center gap-1 text-xs" data-testid="scheme-parts">
          {scheme.fields.map((f) => (
            <li key={f.code} className="rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-content-primary">
              {fieldLabel(labels, f)}
            </li>
          ))}
        </ol>
        <p className="text-xs text-content-tertiary">
          {ui(t, 'design.ui.setup.status_not_in_number')}
          {scheme.source_url && (
            <a className="ml-1 text-oe-blue-text underline" href={scheme.source_url} target="_blank" rel="noreferrer noopener">
              {scheme.source_title || ui(t, 'design.ui.source')}
            </a>
          )}
          {scheme.review_status !== 'verified' && <span className="ml-1 italic">{ui(t, 'design.ui.unconfirmed')}</span>}
        </p>
        {setup.previous_schemes.length > 0 && (
          <p className="text-xs text-content-secondary" data-testid="previous-schemes">
            {ui(t, 'design.ui.setup.previous', { schemes: fmtList(setup.previous_schemes.map((s) => s.id)) })}
          </p>
        )}
      </section>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 rounded-lg border border-border-light p-4 text-sm sm:grid-cols-2" data-testid="setup-settings">
        <div>
          <dt className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.four_eyes')}</dt>
          <dd className="text-content-primary">{setup.four_eyes_release ? ui(t, 'design.ui.yes') : ui(t, 'design.ui.no')}</dd>
        </div>
        <div>
          <dt className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.default_purpose')}</dt>
          <dd className="text-content-primary">{vocab(t, PURPOSE, setup.default_distribution_purpose)}</dd>
        </div>
        <div>
          <dt className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.lead_designer')}</dt>
          <dd className="text-content-primary">{roleTitle(ctx, setup.lead_designer_role_id) || ui(t, 'design.ui.setup.not_set')}</dd>
        </div>
        <div>
          <dt className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.hierarchical')}</dt>
          <dd className="text-content-primary">
            {setup.hierarchical_codes ? ui(t, 'design.ui.setup.hierarchical_on', { separator: setup.wbs_separator }) : ui(t, 'design.ui.no')}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-content-secondary">{ui(t, 'design.ui.setup.targets')}</dt>
          <dd className="text-content-primary">
            {targets.length === 0
              ? ui(t, 'design.ui.setup.not_set')
              : fmtList(
                  targets.map((p) =>
                    ui(t, 'design.ui.setup.target_shown', { phase: phaseName(labels, phases, p.code), status: setup.target_suitability[p.code] }),
                  ),
                )}
          </dd>
        </div>
      </dl>

      {dialog === 'settings' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.setup.edit')}
          fields={settingsFields}
          initial={settings}
          submitLabel={ui(t, 'design.ui.action.save')}
          submit={(values) => updateSetup(ctx.projectId, settingsBody(values))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="settings-form"
        />
      )}
      {dialog === 'scheme' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.setup.scheme_change')}
          subtitle={ui(t, 'design.ui.setup.scheme_change_body')}
          fields={[
            {
              name: 'scheme',
              label: ui(t, 'design.ui.setup.scheme_new'),
              type: 'select',
              required: true,
              options: others.map((s) => ({ value: choiceValue(s), label: schemeChoice(labels, s) })),
            },
          ]}
          initial={{ scheme: '' }}
          submitLabel={ui(t, 'design.ui.setup.scheme_change')}
          submit={async (values) => {
            const result = await changeScheme(ctx.projectId, parseChoice(str(values, 'scheme')));
            const kept = Number(result.legacy_drawings ?? 0);
            if (kept > 0) addToast({ type: 'info', title: uiCount(t, 'design.ui.setup.scheme_changed', kept) }, { duration: 12000 });
          }}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="scheme-form"
        />
      )}
    </div>
  );
}
