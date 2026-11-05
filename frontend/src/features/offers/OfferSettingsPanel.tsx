/** Settings > Company & documents: how offers are numbered, their defaults, and the text library. */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import {
  TEXT_KINDS,
  insertAt,
  useDeleteTextBlock,
  useOfferSettings,
  useRestoreTexts,
  useSaveOfferSettings,
  useSaveTextBlock,
  useTextBlocks,
  type TextBlock,
  type TextKind,
} from './api';
import { PlaceholderChips } from './offerParts';

const inputCls =
  'h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm focus:border-oe-blue focus:outline-none';
const MARKETS = ['DE', 'GB', 'FR', 'US'] as const;

/** Whether a numbering pattern keeps a sequence part, which every pattern must. */
export function patternHasSequence(pattern: string): boolean {
  return /\{seq(:\d+)?\}/.test(pattern) || pattern.includes('{seq');
}

export function OfferSettingsPanel() {
  return (
    <div className="space-y-4" data-testid="offer-settings">
      <NumberingCard />
      <TextLibraryCard />
    </div>
  );
}

function NumberingCard() {
  const { t } = useTranslation();
  const q = useOfferSettings();
  const save = useSaveOfferSettings();
  const [pattern, setPattern] = useState('');
  const [validity, setValidity] = useState('');
  const [paymentDays, setPaymentDays] = useState('');
  useEffect(() => {
    if (q.data) {
      setPattern(q.data.number_pattern);
      setValidity(q.data.validity_days?.toString() ?? '');
      setPaymentDays(q.data.payment_days?.toString() ?? '');
    }
  }, [q.data]);
  const valid = patternHasSequence(pattern);
  return (
    <Card padding="md">
      <h2 className="mb-3 text-sm font-semibold">{t('offers.settings.company.offer_numbering', { defaultValue: 'Numbering and defaults' })}</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm sm:col-span-3">
          {t('offers.settings.number_pattern', { defaultValue: 'Number pattern' })}
          <input className={inputCls} value={pattern} onChange={(e) => setPattern(e.target.value)} />
          <span className="text-xs text-content-tertiary">
            {valid
              ? t('offers.settings.next_number', { number: q.data?.next_number ?? '', defaultValue: 'Next number: {{number}}' })
              : t('offers.settings.pattern_needs_seq', { defaultValue: 'The pattern needs a {seq} part.' })}
          </span>
        </label>
        <label className="text-sm">
          {t('offers.settings.validity_days', { defaultValue: 'Default validity (days)' })}
          <input className={inputCls} inputMode="numeric" value={validity} onChange={(e) => setValidity(e.target.value.replace(/\D/g, ''))} />
        </label>
        <label className="text-sm">
          {t('offers.settings.payment_days', { defaultValue: 'Default payment term (days)' })}
          <input className={inputCls} inputMode="numeric" value={paymentDays} onChange={(e) => setPaymentDays(e.target.value.replace(/\D/g, ''))} />
        </label>
      </div>
      <Button
        className="mt-3"
        size="sm"
        disabled={!valid || save.isPending}
        onClick={() =>
          save.mutate({
            number_pattern: pattern,
            validity_days: validity ? Number(validity) : null,
            payment_days: paymentDays ? Number(paymentDays) : null,
          })
        }
      >
        {t('common.save', { defaultValue: 'Save' })}
      </Button>
    </Card>
  );
}

function TextLibraryCard() {
  const { t } = useTranslation();
  const q = useTextBlocks();
  const save = useSaveTextBlock();
  const del = useDeleteTextBlock();
  const restore = useRestoreTexts();
  const [market, setMarket] = useState<string>(MARKETS[0]);
  const company = (q.data ?? []).filter((b) => b.scope === 'company');

  return (
    <Card padding="md">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t('offers.settings.company.offer_texts_title', { defaultValue: 'Offer texts' })}</h2>
          <p className="text-xs text-content-tertiary">
            {t('offers.settings.company.offer_texts_subtitle', { defaultValue: 'Texts every offer starts from. Projects can override them.' })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select className={`${inputCls} w-20`} value={market} onChange={(e) => setMarket(e.target.value)} aria-label={t('offers.settings.market', { defaultValue: 'Market' })}>
            {MARKETS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <Button size="sm" variant="secondary" disabled={restore.isPending} onClick={() => restore.mutate(market)}>
            {t('offers.settings.restore_defaults', { defaultValue: 'Restore market defaults' })}
          </Button>
        </div>
      </div>
      <div className="mt-3 space-y-5">
        {TEXT_KINDS.map((kind) => (
          <KindGroup
            key={kind}
            kind={kind}
            blocks={company.filter((b) => b.kind === kind)}
            onSave={(b) => save.mutate(b)}
            onDelete={(id) => del.mutate(id)}
          />
        ))}
      </div>
    </Card>
  );
}

function KindGroup({ kind, blocks, onSave, onDelete }: { kind: TextKind; blocks: TextBlock[]; onSave: (b: Partial<TextBlock> & { kind: TextKind }) => void; onDelete: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <section>
      <h3 className="mb-1 text-sm font-medium">{t(`offers.texts.kind.${kind}`, { defaultValue: kind })}</h3>
      {blocks.map((b) => (
        <BlockEditor key={b.id} block={b} onSave={onSave} onDelete={onDelete} />
      ))}
      <Button size="sm" variant="ghost" onClick={() => onSave({ kind, name: '', language: 'en', body: '', scope: 'company', is_default: blocks.length === 0 })}>
        {t('offers.settings.add_text', { defaultValue: 'Add text' })}
      </Button>
    </section>
  );
}

function BlockEditor({ block, onSave, onDelete }: { block: TextBlock; onSave: (b: Partial<TextBlock> & { kind: TextKind }) => void; onDelete: (id: string) => void }) {
  const { t } = useTranslation();
  const [body, setBody] = useState(block.body);
  const [lang, setLang] = useState(block.language);
  useEffect(() => {
    setBody(block.body);
    setLang(block.language);
  }, [block.body, block.language]);
  let area: HTMLTextAreaElement | null = null;
  const commit = () => {
    if (body !== block.body || lang !== block.language) onSave({ ...block, body, language: lang });
  };
  return (
    <div className="mb-2 rounded-md border border-border-light p-2">
      <div className="mb-1 flex items-center gap-2">
        <input className={`${inputCls} w-20`} value={lang} maxLength={10} onChange={(e) => setLang(e.target.value.toLowerCase())} onBlur={commit} aria-label={t('offers.document_language', { defaultValue: 'Document language' })} />
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={block.is_default} onChange={(e) => onSave({ ...block, body, is_default: e.target.checked })} />
          {t('offers.settings.default_text', { defaultValue: 'Default' })}
        </label>
        <button type="button" className="ml-auto text-xs text-semantic-error underline" onClick={() => onDelete(block.id)}>
          {t('common.delete', { defaultValue: 'Delete' })}
        </button>
      </div>
      <PlaceholderChips
        onInsert={(token) => setBody(insertAt(body, area?.selectionStart ?? body.length, area?.selectionEnd ?? body.length, token).text)}
      />
      <textarea ref={(el) => { area = el; }} className={`${inputCls} h-20 py-2`} value={body} onChange={(e) => setBody(e.target.value)} onBlur={commit} />
    </div>
  );
}
