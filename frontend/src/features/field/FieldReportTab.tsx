// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * "Report from site": one place to raise a punch item, an NCR, a safety
 * observation or a haul ticket. Punch keeps its own form (photo, GPS); the other
 * three are short forms that queue like every other capture and land once when
 * the signal returns.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import { newClientOpId } from '@/shared/lib/offline';
import type { EnqueueInput } from '@/shared/lib/offline';
import { FieldRaiseIssueTab } from './FieldRaiseIssueTab';
import { REPORT_KINDS, buildHaulOp, buildNcrOp, buildSafetyOp, type ReportKind } from './fieldKinds';

type Enqueue = (input: EnqueueInput) => Promise<void>;
type RaiseProps = Parameters<typeof FieldRaiseIssueTab>[0];
type Level = 1 | 3 | 5;

const inputCls = 'h-12 w-full rounded-xl border border-slate-300 bg-white px-3 text-base text-slate-900';
const areaCls = 'min-h-[88px] w-full rounded-xl border border-slate-300 bg-white p-3 text-base text-slate-900';
const labelCls = 'flex flex-col gap-1 text-sm font-medium text-slate-700';

const LEVELS = [
  { value: 1, key: 'low', fallback: 'Low' },
  { value: 3, key: 'medium', fallback: 'Medium' },
  { value: 5, key: 'high', fallback: 'High' },
] as const;
const SAFETY_TYPES = ['positive', 'unsafe_act', 'unsafe_condition', 'near_miss'] as const;
const SAFETY_TYPE_FALLBACK: Record<(typeof SAFETY_TYPES)[number], string> = {
  positive: 'Good practice',
  unsafe_act: 'Unsafe act',
  unsafe_condition: 'Unsafe condition',
  near_miss: 'Near miss',
};
const KIND_LABEL_FALLBACK: Record<ReportKind, string> = {
  punch: 'Punch item',
  ncr: 'Non-conformance',
  safety_observation: 'Safety observation',
  haul_ticket: 'Haul ticket',
};

function Saved() {
  const { t } = useTranslation();
  return (
    <p role="status" data-testid="report-saved" className="flex items-center gap-2 text-sm text-emerald-700">
      <Check size={16} aria-hidden="true" />
      {t('field.report.saved', { defaultValue: 'Saved on this device. It will sync when there is signal.' })}
    </p>
  );
}

function SaveButton({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  return (
    <button
      type="submit"
      disabled={disabled}
      data-testid="report-save"
      className="h-14 rounded-xl bg-sky-600 text-base font-semibold text-white disabled:opacity-50"
    >
      {t('field.report.save', { defaultValue: 'Save' })}
    </button>
  );
}

function LevelPicker({ value, onChange, label }: { value: Level; onChange: (v: Level) => void; label: string }) {
  const { t } = useTranslation();
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-sm font-medium text-slate-700">{label}</legend>
      <div className="flex gap-2">
        {LEVELS.map((l) => (
          <button
            key={l.value}
            type="button"
            aria-pressed={value === l.value}
            onClick={() => onChange(l.value)}
            className={`h-12 flex-1 rounded-xl border text-sm font-medium ${
              value === l.value ? 'border-sky-600 bg-sky-600 text-white' : 'border-slate-300 bg-white text-slate-700'
            }`}
          >
            {t(`field.report.level_${l.key}`, { defaultValue: l.fallback })}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function NcrForm({ enqueue }: { enqueue: Enqueue }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [level, setLevel] = useState<Level>(1);
  const severity = level === 5 ? 'critical' : level === 3 ? 'major' : 'minor';

  const submit = async () => {
    await enqueue(buildNcrOp({ title, description, severity, capturedAt: new Date().toISOString() }, newClientOpId()));
    setTitle('');
    setDescription('');
    setSaved(true);
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className={labelCls}>
        {t('field.report.title_label', { defaultValue: 'Title' })}
        <input
          className={inputCls}
          value={title}
          maxLength={500}
          onChange={(e) => {
            setTitle(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className={labelCls}>
        {t('field.report.description_label', { defaultValue: 'Description' })}
        <textarea className={areaCls} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <LevelPicker value={level} onChange={setLevel} label={t('field.report.level_label', { defaultValue: 'Severity' })} />
      {saved && <Saved />}
      <SaveButton disabled={title.trim() === ''} />
    </form>
  );
}

function SafetyForm({ enqueue }: { enqueue: Enqueue }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  const [type, setType] = useState<(typeof SAFETY_TYPES)[number]>('unsafe_condition');
  const [description, setDescription] = useState('');
  const [level, setLevel] = useState<Level>(3);

  const submit = async () => {
    await enqueue(
      buildSafetyOp(
        { observationType: type, description, severity: level, likelihood: 3, capturedAt: new Date().toISOString() },
        newClientOpId(),
      ),
    );
    setDescription('');
    setSaved(true);
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className={labelCls}>
        {t('field.report.safety_type_label', { defaultValue: 'Type' })}
        <select
          className={inputCls}
          value={type}
          onChange={(e) => {
            setType(e.target.value as (typeof SAFETY_TYPES)[number]);
            setSaved(false);
          }}
        >
          {SAFETY_TYPES.map((v) => (
            <option key={v} value={v}>
              {t(`field.report.safety_type_${v}`, { defaultValue: SAFETY_TYPE_FALLBACK[v] })}
            </option>
          ))}
        </select>
      </label>
      <label className={labelCls}>
        {t('field.report.description_label', { defaultValue: 'Description' })}
        <textarea
          className={areaCls}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <LevelPicker value={level} onChange={setLevel} label={t('field.report.level_label', { defaultValue: 'Severity' })} />
      {saved && <Saved />}
      <SaveButton disabled={description.trim() === ''} />
    </form>
  );
}

function HaulForm({ enqueue }: { enqueue: Enqueue }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  const [material, setMaterial] = useState('');
  const [net, setNet] = useState('');
  const [plate, setPlate] = useState('');
  const build = () =>
    buildHaulOp(
      { materialName: material, netT: net, plate, direction: 'inbound', capturedAt: new Date().toISOString() },
      newClientOpId(),
    );
  const netInvalid = net.trim() !== '' && build() === null;

  const submit = async () => {
    const op = build();
    if (!op) return;
    await enqueue(op);
    setMaterial('');
    setNet('');
    setPlate('');
    setSaved(true);
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className={labelCls}>
        {t('field.report.haul_material', { defaultValue: 'Material' })}
        <input
          className={inputCls}
          value={material}
          onChange={(e) => {
            setMaterial(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className={labelCls}>
        {t('field.report.haul_net_t', { defaultValue: 'Net weight (t)' })}
        <input
          className={`${inputCls} ${netInvalid ? 'border-rose-500' : ''}`}
          inputMode="decimal"
          aria-invalid={netInvalid}
          value={net}
          onChange={(e) => {
            setNet(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className={labelCls}>
        {t('field.report.haul_plate', { defaultValue: 'Vehicle plate' })}
        <input className={inputCls} value={plate} onChange={(e) => setPlate(e.target.value)} />
      </label>
      {saved && <Saved />}
      <SaveButton disabled={material.trim() === '' || netInvalid} />
    </form>
  );
}

export function FieldReportTab(props: RaiseProps) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<ReportKind>('punch');

  return (
    <div className="flex flex-1 flex-col">
      <div role="tablist" className="grid grid-cols-2 gap-2 px-4 pt-4 sm:grid-cols-4">
        {REPORT_KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            data-testid={`report-kind-${k}`}
            onClick={() => setKind(k)}
            className={`min-h-[44px] rounded-xl border px-2 text-sm font-medium ${
              kind === k ? 'border-sky-600 bg-sky-600 text-white' : 'border-slate-300 bg-white text-slate-700'
            }`}
          >
            {t(`field.report.kind_${k}`, { defaultValue: KIND_LABEL_FALLBACK[k] })}
          </button>
        ))}
      </div>
      {kind === 'punch' ? (
        <FieldRaiseIssueTab {...props} />
      ) : (
        <div className="px-4 py-4">
          {kind === 'ncr' && <NcrForm enqueue={props.enqueue} />}
          {kind === 'safety_observation' && <SafetyForm enqueue={props.enqueue} />}
          {kind === 'haul_ticket' && <HaulForm enqueue={props.enqueue} />}
        </div>
      )}
    </div>
  );
}

export default FieldReportTab;
