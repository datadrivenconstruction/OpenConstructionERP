import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Check, ChevronLeft, ChevronRight } from 'lucide-react';
import { getLatestLayout, LayoutGetResponse } from '@/acap/floorPlanApi';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import type { FloorPlan } from '@/acap/planTypes';
import {
  STEP_COUNT,
  STEP_TITLES,
  deriveStepAvailability,
} from './studioSteps';
import { StepPending } from './StepPending';
import { UploadStep } from './UploadStep';
import { ConfirmStep } from './ConfirmStep';
import { RabStep } from './RabStep';
import { TimelineStep } from './TimelineStep';
import { ThreeDStep } from './ThreeDStep';
import { InteriorStep } from './InteriorStep';
import type { ExtractResponse } from './studioApi';

type LayoutProbe =
  | { status: 'loading' }
  | { status: 'ready'; hasLayout: boolean }
  | { status: 'error'; message: string };

export default function StudioPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [probe, setProbe] = useState<LayoutProbe>({ status: 'loading' });
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState<FloorPlan | null>(null);
  const [extractInfo, setExtractInfo] = useState<ExtractResponse | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setProbe({ status: 'loading' });
    getLatestLayout(projectId)
      .then((res: LayoutGetResponse) => {
        if (cancelled) return;
        setProbe({ status: 'ready', hasLayout: Boolean(res?.plan?.levels?.length) });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setProbe({ status: 'ready', hasLayout: false });
        } else {
          setProbe({ status: 'error', message: getErrorMessage(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleExtracted = useCallback((resp: ExtractResponse) => {
    setDraft(resp.draft_plan);
    setExtractInfo(resp);
    setStep(2);
  }, []);

  const handleDraftChange = useCallback((plan: FloorPlan) => {
    setDraft(plan);
  }, []);

  const handleSaved = useCallback((_version: number) => {
    setProbe({ status: 'ready', hasLayout: true });
    setStep(4);
  }, []);

  const hasLayout = probe.status === 'ready' && probe.hasLayout;
  const maxStep = deriveStepAvailability({ hasLayout }).maxStep;

  const canGoBack = step > 1;
  const canGoNext = step < maxStep;

  if (!projectId) return null;

  if (probe.status === 'loading') {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-sm text-content-secondary">Memuat Studio…</div>
      </div>
    );
  }

  if (probe.status === 'error') {
    return (
      <div className="p-6 text-sm text-semantic-error">{probe.message}</div>
    );
  }

  const renderStepBody = () => {
    switch (step) {
      case 1:
        return <UploadStep projectId={projectId} onExtracted={handleExtracted} />;
      case 2:
        return extractInfo ? (
          <div className="flex flex-col gap-4">
            <div className="rounded-md border border-surface-secondary bg-surface-secondary p-4 text-sm text-content-secondary">
              Ekstraksi selesai menggunakan model {extractInfo.model}.
              {extractInfo.valid
                ? ' Layout tervalidasi.'
                : ' Beberapa ruangan perlu dirapikan.'}
            </div>
            <button
              type="button"
              onClick={() => setStep(3)}
              className="self-start rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover"
            >
              Lanjut ke Konfirmasi
            </button>
          </div>
        ) : (
          <StepPending title={STEP_TITLES[step - 1]} />
        );
      case 3:
        return draft ? (
          <ConfirmStep
            draft={draft}
            onDraftChange={handleDraftChange}
            projectId={projectId}
            onSaved={handleSaved}
          />
        ) : (
          <StepPending title={STEP_TITLES[step - 1]} />
        );
      case 4:
        return <RabStep projectId={projectId} />;
      case 5:
        return <TimelineStep projectId={projectId} />;
      case 6:
        return <ThreeDStep projectId={projectId} />;
      case 7:
        return <InteriorStep projectId={projectId} />;
      default:
        return <StepPending title={STEP_TITLES[step - 1]} />;
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Stepper — dot-grid mirroring CreateProjectPage.tsx:1186-1218 */}
      <div className="relative">
        <div className="absolute left-3 right-3 top-3 h-px bg-border-light" />
        <div
          className="relative grid"
          style={{ gridTemplateColumns: `repeat(${STEP_COUNT}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: STEP_COUNT }, (_, i) => i + 1).map((s) => {
            const navigable = s <= maxStep && s !== step;
            const dotCls = `flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ring-4 ring-surface-elevated transition-colors ${
              s < step
                ? 'bg-oe-blue text-white'
                : s === step
                  ? 'bg-oe-blue text-white ring-oe-blue/25'
                  : s <= maxStep
                    ? 'bg-surface-secondary text-content-tertiary border border-border-light'
                    : 'bg-surface-secondary text-content-quaternary border border-border-light opacity-60'
            }`;
            return (
              <div key={s} className="flex flex-col items-center gap-1.5 min-w-0">
                {navigable ? (
                  <button
                    type="button"
                    onClick={() => setStep(s)}
                    aria-label={STEP_TITLES[s - 1]}
                    className={dotCls + ' cursor-pointer hover:opacity-90'}
                  >
                    {s < step ? <Check size={13} /> : s}
                  </button>
                ) : (
                  <div
                    className={dotCls}
                    aria-current={s === step ? 'step' : undefined}
                  >
                    {s < step ? <Check size={13} /> : s}
                  </div>
                )}
                <span
                  className={`hidden sm:block text-[10px] leading-tight text-center truncate max-w-[88px] ${
                    s === step
                      ? 'text-content-secondary font-medium'
                      : s <= maxStep
                        ? 'text-content-quaternary'
                        : 'text-content-quaternary/60'
                  }`}
                >
                  {STEP_TITLES[s - 1]}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Step body */}
      <div className="rounded-xl border border-border-light bg-surface-elevated p-6">
        {renderStepBody()}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => canGoBack && setStep((s) => Math.max(1, s - 1))}
          disabled={!canGoBack}
          className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={16} />
          Kembali
        </button>
        <button
          type="button"
          onClick={() => canGoNext && setStep((s) => Math.min(maxStep, s + 1))}
          disabled={!canGoNext}
          className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Lanjut
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}