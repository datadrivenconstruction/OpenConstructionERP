// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Assessing a stakeholder. The method names the scales; the reader scores
// each one and says how engaged the stakeholder is today and how engaged the
// project needs them to be. The class is derived from the scores by the
// framework's rules and shown as a preview; the server stores its own.
// An assessment is never edited, a new one is added on top.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import { createAssessment, type Assessment, type Scores, type Stakeholder } from './api';
import { FIELD_CLASS, RefusalBox, useWrite } from './StakeholderBits';
import { itemName, nameOf, type KeyText } from './labels';
import { defaultScores, previewClassification } from './rules';
import { stakeholderName, type Screen } from './screen';

export const ATTITUDE: Record<string, KeyText> = {
  '-2': ['stakeholders.ui.attitude.minus_2', 'Strongly against'],
  '-1': ['stakeholders.ui.attitude.minus_1', 'Against'],
  '0': ['stakeholders.ui.attitude.zero', 'Neutral'],
  '1': ['stakeholders.ui.attitude.plus_1', 'In favour'],
  '2': ['stakeholders.ui.attitude.plus_2', 'Strongly in favour'],
};

export interface AssessmentDialogProps {
  screen: Screen;
  stakeholder: Stakeholder;
  /** The newest assessment, whose values the form starts from. */
  previous: Assessment | null;
  onClose: () => void;
  onSaved: () => void;
}

export function AssessmentDialog({ screen, stakeholder, previous, onClose, onSaved }: AssessmentDialogProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels } = screen;
  const fw = settings.framework;
  const [methodCode, setMethodCode] = useState(settings.analysis_method);
  const method = useMemo(
    () => fw.analysis_methods.find((m) => m.code === methodCode) ?? fw.analysis_methods[0] ?? null,
    [fw, methodCode],
  );
  const startScores = (code: string): Scores => {
    const m = fw.analysis_methods.find((x) => x.code === code);
    if (!m) return {};
    return previous && previous.method_code === code ? { ...defaultScores(m), ...previous.scores } : defaultScores(m);
  };
  const [scores, setScores] = useState<Scores>(() => startScores(settings.analysis_method));
  const [current, setCurrent] = useState(previous?.engagement_current ?? stakeholder.engagement_current ?? '');
  const [desired, setDesired] = useState(previous?.engagement_desired ?? stakeholder.engagement_desired ?? '');
  const [attitude, setAttitude] = useState(previous?.attitude != null ? String(previous.attitude) : '');
  const [rationale, setRationale] = useState('');

  const write = useWrite(
    () =>
      createAssessment(projectId, stakeholder.id, {
        method_code: methodCode,
        scores,
        engagement_current: current || null,
        engagement_desired: desired || null,
        attitude: attitude === '' ? null : Number(attitude),
        rationale: rationale.trim(),
      }),
    onSaved,
  );

  const preview = method ? previewClassification(method, scores) : null;
  const levels = [...fw.engagement_levels].sort((a, b) => a.order - b.order);

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="lg"
      testId="assessment-dialog"
      title={t('stakeholders.ui.assessment.title', { defaultValue: 'Assess stakeholder' })}
      subtitle={stakeholderName(t, stakeholder)}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {preview && (
            <p className="mr-auto text-sm text-content-secondary" data-testid="assessment-preview">
              {t('stakeholders.ui.assessment.preview', {
                defaultValue: 'These scores are classified as: {{classification}}',
                classification: nameOf(labels, method?.classes ?? [], preview),
              })}
            </p>
          )}
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!method} onClick={() => write.run(undefined)} data-testid="assessment-save">
            {t('stakeholders.ui.assessment.save', { defaultValue: 'Save assessment' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox refusal={write.refusal} />
        {fw.analysis_methods.length > 1 && (
          <WideModalField
            label={t('stakeholders.ui.assessment.method', { defaultValue: 'Analysis method' })}
            htmlFor="assessment-method"
          >
            <select
              id="assessment-method"
              className={FIELD_CLASS}
              value={methodCode}
              onChange={(e) => {
                setMethodCode(e.target.value);
                setScores(startScores(e.target.value));
              }}
            >
              {fw.analysis_methods.map((m) => (
                <option key={m.code} value={m.code}>
                  {itemName(labels, m)}
                </option>
              ))}
            </select>
          </WideModalField>
        )}

        <WideModalSection title={t('stakeholders.ui.assessment.scores', { defaultValue: 'Scores' })} columns={2}>
          {(method?.dimensions ?? []).map((d) =>
            d.type === 'bool' ? (
              <label key={d.code} className="flex items-center gap-2 text-sm text-content-primary">
                <input
                  type="checkbox"
                  checked={scores[d.code] === true}
                  onChange={(e) => setScores((s) => ({ ...s, [d.code]: e.target.checked }))}
                />
                {itemName(labels, d)}
              </label>
            ) : (
              <WideModalField
                key={d.code}
                label={itemName(labels, d)}
                hint={t('stakeholders.ui.assessment.scale', {
                  defaultValue: '{{min}} is the lowest, {{max}} the highest',
                  min: d.min,
                  max: d.max,
                })}
                htmlFor={`score-${d.code}`}
              >
                <select
                  id={`score-${d.code}`}
                  className={FIELD_CLASS}
                  value={String(scores[d.code] ?? d.min)}
                  onChange={(e) => setScores((s) => ({ ...s, [d.code]: Number(e.target.value) }))}
                >
                  {Array.from({ length: d.max - d.min + 1 }, (_, i) => d.min + i).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </WideModalField>
            ),
          )}
        </WideModalSection>

        <WideModalSection
          title={t('stakeholders.ui.assessment.engagement', { defaultValue: 'Engagement' })}
          description={t('stakeholders.ui.assessment.engagement_hint', {
            defaultValue: 'Where the stakeholder stands today and where the project needs them. The difference is the gap the communication plan closes.',
          })}
          columns={3}
        >
          <WideModalField
            label={t('stakeholders.ui.assessment.current', { defaultValue: 'Today' })}
            htmlFor="assessment-current"
          >
            <select
              id="assessment-current"
              className={FIELD_CLASS}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            >
              <option value="">{t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}</option>
              {levels.map((l) => (
                <option key={l.code} value={l.code}>
                  {itemName(labels, l)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.assessment.desired', { defaultValue: 'Needed' })}
            htmlFor="assessment-desired"
          >
            <select
              id="assessment-desired"
              className={FIELD_CLASS}
              value={desired}
              onChange={(e) => setDesired(e.target.value)}
            >
              <option value="">{t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}</option>
              {levels.map((l) => (
                <option key={l.code} value={l.code}>
                  {itemName(labels, l)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.assessment.attitude', { defaultValue: 'Attitude to the project' })}
            htmlFor="assessment-attitude"
          >
            <select
              id="assessment-attitude"
              className={FIELD_CLASS}
              value={attitude}
              onChange={(e) => setAttitude(e.target.value)}
            >
              <option value="">{t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}</option>
              {Object.entries(ATTITUDE)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([value, text]) => (
                  <option key={value} value={value}>
                    {t(text[0], { defaultValue: text[1] })}
                  </option>
                ))}
            </select>
          </WideModalField>
        </WideModalSection>

        <WideModalField
          label={t('stakeholders.ui.assessment.rationale', { defaultValue: 'Why you see it this way' })}
          htmlFor="assessment-rationale"
        >
          <textarea
            id="assessment-rationale"
            rows={3}
            className={FIELD_CLASS}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </WideModalField>
      </div>
    </WideModal>
  );
}
