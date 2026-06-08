/**
 * Subcontractor prequalification questionnaire modal.
 *
 * Wave 4 / T12 — subcontractor-prequalification-platform-style yes/no questionnaire. The
 * answers are submitted as a flat ``Record<string, "yes" | "no">`` to
 * the ``POST /v1/subcontractors/{id}/prequal`` endpoint; the backend
 * derives the numeric score (0-100, % of Yes answers) when none is
 * supplied. The form deliberately keeps the question set short and
 * generic so different GCs can adopt it without a custom schema —
 * project-specific questionnaires live in a separate (future) module.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { ClipboardCheck, Loader2 } from 'lucide-react';
import {
  Button,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { submitPrequal, type Subcontractor } from './api';

interface QuestionDef {
  key: string;
  /** i18n key */
  i18nKey: string;
  defaultText: string;
  /** When true, "Yes" answers REDUCE the score (e.g. "Has had incidents?"). */
  negative?: boolean;
}

/**
 * The generic 7-question prequal questionnaire. Real subcontractor
 * prequalification platform templates pull from a per-org Q-bank — we ship a sensible
 * default so the feature works out of the box; future iterations can
 * source this from a tenant-scoped table.
 */
const QUESTIONS: QuestionDef[] = [
  {
    key: 'license_current',
    i18nKey: 'subcontractors.prequal_q_license',
    defaultText: 'Is your contractor license current and in good standing?',
  },
  {
    key: 'wcb_coverage',
    i18nKey: 'subcontractors.prequal_q_wcb',
    defaultText: 'Do you carry workers compensation (WCB) coverage?',
  },
  {
    key: 'insurance_current',
    i18nKey: 'subcontractors.prequal_q_insurance',
    defaultText: 'Do you carry general liability insurance current to today?',
  },
  {
    key: 'safety_program',
    i18nKey: 'subcontractors.prequal_q_safety',
    defaultText: 'Do you have a written health & safety program?',
  },
  {
    key: 'references_available',
    i18nKey: 'subcontractors.prequal_q_refs',
    defaultText: 'Can you provide references for 3+ recent comparable projects?',
  },
  {
    key: 'has_open_incidents',
    i18nKey: 'subcontractors.prequal_q_incidents',
    defaultText: 'Have you had any reportable HSE incidents in the past 24 months?',
    negative: true,
  },
  {
    key: 'has_unpaid_liens',
    i18nKey: 'subcontractors.prequal_q_liens',
    defaultText: 'Are there any unresolved mechanic\'s liens against your company?',
    negative: true,
  },
];

type AnswerValue = 'yes' | 'no' | '';

type Answers = Record<string, AnswerValue>;

interface PrequalModalProps {
  subcontractor: Subcontractor;
  onClose: () => void;
}

/**
 * Compute a 0-100 score from the current answers — runs client-side as
 * a *preview* so the user sees where they're tracking before submit.
 * The authoritative score is recomputed on the server (or supplied by
 * the caller in the API payload). Positive Q's: Yes = +1 point.
 * Negative Q's: No = +1 point (a "Yes" to "have you had incidents?"
 * lowers the score).
 */
function _previewScore(answers: Answers): { score: number; answered: number } {
  let positive = 0;
  let counted = 0;
  for (const q of QUESTIONS) {
    const a = answers[q.key];
    if (a !== 'yes' && a !== 'no') continue;
    counted += 1;
    const isYes = a === 'yes';
    if ((!q.negative && isYes) || (q.negative && !isYes)) positive += 1;
  }
  if (counted === 0) return { score: 0, answered: 0 };
  return { score: Math.round((positive / counted) * 100), answered: counted };
}

export function PrequalModal({ subcontractor, onClose }: PrequalModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<Answers>(() => {
    // Seed from any prior questionnaire so the form is editable, not
    // throw-away. Empty / non-matching values fall back to "".
    const prior = (subcontractor.prequal_questionnaire as Answers | null) || {};
    const seeded: Answers = {};
    for (const q of QUESTIONS) {
      const v = prior[q.key];
      seeded[q.key] = v === 'yes' || v === 'no' ? v : '';
    }
    return seeded;
  });

  const { score, answered } = useMemo(() => _previewScore(answers), [answers]);

  const setAnswer = (key: string, value: AnswerValue) =>
    setAnswers((prev) => ({ ...prev, [key]: value }));

  const allAnswered = QUESTIONS.every((q) => answers[q.key] !== '');

  const submit = async () => {
    if (!allAnswered) {
      addToast({
        type: 'error',
        title: t('subcontractors.prequal_answer_all', {
          defaultValue: 'Please answer every question before submitting.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      // Send the raw answers — backend computes a server-trusted score
      // from the Yes/No values. The client-side preview score is just
      // for UX feedback.
      await submitPrequal(subcontractor.id, {
        questionnaire: answers as Record<string, unknown>,
      });
      addToast({
        type: 'success',
        title: t('subcontractors.prequal_submitted', {
          defaultValue: 'Prequalification submitted - score: {{score}}',
          score,
        }),
      });
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      title={t('subcontractors.prequal_modal_title', {
        defaultValue: 'Prequalify {{name}}',
        name: subcontractor.legal_name,
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            disabled={!allAnswered}
            icon={busy ? <Loader2 size={14} /> : <ClipboardCheck size={14} />}
          >
            {t('subcontractors.prequal_submit', {
              defaultValue: 'Submit prequalification',
            })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('subcontractors.prequal_section_title', {
          defaultValue: 'Questionnaire',
        })}
      >
        <div className="space-y-2">
          {QUESTIONS.map((q) => (
            <WideModalField
              key={q.key}
              label={t(q.i18nKey, { defaultValue: q.defaultText })}
              hint={
                q.negative
                  ? t('subcontractors.prequal_negative_hint', {
                      defaultValue: '"Yes" reduces the score for this item.',
                    })
                  : undefined
              }
            >
              <div className="flex gap-2">
                {(['yes', 'no'] as const).map((opt) => {
                  const selected = answers[q.key] === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setAnswer(q.key, opt)}
                      className={clsx(
                        'flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                        selected
                          ? opt === 'yes'
                            ? 'border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200'
                            : 'border-rose-500 bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-200'
                          : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue/40 hover:text-content-primary',
                      )}
                      aria-pressed={selected}
                    >
                      {opt === 'yes'
                        ? t('common.yes', { defaultValue: 'Yes' })
                        : t('common.no', { defaultValue: 'No' })}
                    </button>
                  );
                })}
              </div>
            </WideModalField>
          ))}
        </div>
      </WideModalSection>

      <WideModalSection
        title={t('subcontractors.prequal_preview_title', {
          defaultValue: 'Score preview',
        })}
      >
        <div className="flex items-center justify-between rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
          <div>
            <p className="text-xs text-content-tertiary">
              {t('subcontractors.prequal_preview_label', {
                defaultValue: 'Live score (based on your answers so far)',
              })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('subcontractors.prequal_answered', {
                defaultValue: '{{answered}} of {{total}} answered',
                answered,
                total: QUESTIONS.length,
              })}
            </p>
          </div>
          <p
            className={clsx(
              'text-3xl font-semibold tabular-nums',
              answered === 0
                ? 'text-content-tertiary'
                : score >= 80
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : score >= 50
                    ? 'text-amber-600 dark:text-amber-400'
                    : 'text-rose-600 dark:text-rose-400',
            )}
          >
            {answered === 0 ? '—' : score}
          </p>
        </div>
      </WideModalSection>
    </WideModal>
  );
}
