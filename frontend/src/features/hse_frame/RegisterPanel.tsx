// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Register tab: requirements, reviews, clearances, permit conditions and targets by topic. Each row can be
// closed with a date and a note, waived with a reason, and linked to the records that prove it (a permit
// condition, an incident, a permit to work, a risk assessment, an audit, an inspection).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link2, Plus, X } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';

import {
  addLink,
  createItem,
  deleteItem,
  localToday,
  meetItem,
  removeLink,
  reopenItem,
  waiveItem,
  type Catalogue,
  type Item,
} from './api';
import { useCandidates, type HseWrite } from './hooks';
import { fmtDate } from '@/shared/lib/formatters';
import { ExportButtons } from './ExportButtons';
import { RemoveConfirm, type RemoveTarget } from './RemoveConfirm';
import { groupByTopic, isOpen, itemTitle, labelOf, progress } from './labels';

interface Props {
  projectId: string;
  items: Item[];
  catalogue: Catalogue;
  write: HseWrite;
  canEdit: boolean;
  canManage: boolean;
}

const STATUS_TONE: Record<Item['status'], BadgeVariant> = {
  open: 'warning',
  in_progress: 'blue',
  met: 'success',
  waived: 'neutral',
  not_applicable: 'neutral',
};

function LinkPicker({ projectId, item, catalogue, write }: { projectId: string; item: Item; catalogue: Catalogue; write: HseWrite }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState(catalogue.link_kinds[0] ?? '');
  const [q, setQ] = useState('');
  const candidates = useCandidates(projectId, kind, q);
  const [pick, setPick] = useState('');
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2" data-testid={`link-picker-${item.id}`}>
      <label className="flex flex-col gap-1 text-xs text-content-secondary">
        {t('hseFrame.link.kind', { defaultValue: 'Record kind' })}
        <select className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm" value={kind} onChange={(e) => { setKind(e.target.value); setPick(''); }}>
          {catalogue.link_kinds.map((k) => (
            <option key={k} value={k}>
              {t(`hseFrame.link_kind.${k}`, { defaultValue: k.replace(/_/g, ' ') })}
            </option>
          ))}
        </select>
      </label>
      <Input label={t('hseFrame.link.search', { defaultValue: 'Search' })} value={q} onChange={(e) => setQ(e.target.value)} />
      <label className="flex flex-col gap-1 text-xs text-content-secondary">
        {t('hseFrame.link.record', { defaultValue: 'Record' })}
        <select className="h-9 min-w-48 rounded-lg border border-border bg-surface-primary px-2 text-sm" value={pick} onChange={(e) => setPick(e.target.value)} data-testid="link-candidate">
          <option value="">{t('hseFrame.link.choose', { defaultValue: 'Choose a record' })}</option>
          {(candidates.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {[c.number, c.title, c.status].filter(Boolean).join(' | ')}
            </option>
          ))}
        </select>
      </label>
      <Button
        size="sm"
        variant="secondary"
        disabled={!pick || write.pending}
        onClick={() => write.send(() => addLink(projectId, item.id, { link_kind: kind, link_id: pick }), () => setPick(''))}
        data-testid="link-add"
      >
        {t('hseFrame.link.add', { defaultValue: 'Link' })}
      </Button>
    </div>
  );
}

function ItemRow({ projectId, item, catalogue, write, canEdit, canManage, onRemove }: Props & { item: Item; onRemove: (target: RemoveTarget) => void }) {
  const { t, i18n } = useTranslation();
  const [panel, setPanel] = useState<'none' | 'meet' | 'waive' | 'link'>('none');
  const [note, setNote] = useState('');
  const [day, setDay] = useState(localToday());
  const open = isOpen(item.status);
  return (
    <li className="rounded-lg border border-border-light p-3" data-testid={`item-${item.id}`} data-status={item.status}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-content-primary">{itemTitle(item, catalogue, i18n.language)}</p>
          <p className="text-xs text-content-secondary">
            {[
              item.legal_basis,
              item.responsible_party,
              item.due_date && t('hseFrame.item.due', { defaultValue: 'due {{date}}', date: fmtDate(item.due_date) }),
              item.obligation === 'recommended' && t('hseFrame.item.recommended', { defaultValue: 'recommended' }),
              item.in_tender_documents && t('hseFrame.item.in_tender', { defaultValue: 'part of the tender documents' }),
            ]
              .filter(Boolean)
              .join(' | ')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {item.overdue && <Badge variant="error">{t('hseFrame.item.overdue', { defaultValue: 'Overdue' })}</Badge>}
          <Badge variant={STATUS_TONE[item.status]}>{t(`hseFrame.item_status.${item.status}`, { defaultValue: item.status.replace('_', ' ') })}</Badge>
        </div>
      </div>
      {item.links.length > 0 && (
        <ul className="mt-2 space-y-1" data-testid={`item-links-${item.id}`}>
          {item.links.map((l) => (
            <li key={l.id} className="flex items-center gap-2 text-xs text-content-secondary">
              <Link2 size={12} aria-hidden />
              <span>
                {t(`hseFrame.link_kind.${l.link_kind}`, { defaultValue: l.link_kind.replace(/_/g, ' ') })}
                {l.fact ? `: ${[l.fact.number, l.fact.title, l.fact.status].filter(Boolean).join(' | ')}` : ''}
              </span>
              {canEdit && (
                <button type="button" className="text-content-tertiary hover:text-semantic-error" aria-label={t('hseFrame.link.remove', { defaultValue: 'Remove link' })} onClick={() => onRemove({ name: [t(`hseFrame.link_kind.${l.link_kind}`, { defaultValue: l.link_kind.replace(/_/g, ' ') }), l.fact?.number].filter(Boolean).join(' '), run: () => removeLink(projectId, item.id, l.id) })}>
                  <X size={12} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {item.status === 'met' && (item.evidence_note || item.met_on) && (
        <p className="mt-1 text-xs text-content-secondary">
          {[item.met_on && t('hseFrame.item.met_on_short', { defaultValue: 'met on {{date}}', date: fmtDate(item.met_on) }), item.evidence_note].filter(Boolean).join(' | ')}
        </p>
      )}
      {(item.status === 'waived' || item.status === 'not_applicable') && (
        <p className="mt-1 text-xs text-content-secondary">{item.waive_reason}</p>
      )}
      {canEdit && (
        <div className="mt-2 flex flex-wrap gap-2">
          {open && (
            <Button size="sm" variant="secondary" onClick={() => setPanel(panel === 'meet' ? 'none' : 'meet')} data-testid="item-meet">
              {t('hseFrame.item.meet', { defaultValue: 'Mark met' })}
            </Button>
          )}
          {open && canManage && (
            <Button size="sm" variant="ghost" onClick={() => setPanel(panel === 'waive' ? 'none' : 'waive')} data-testid="item-waive">
              {t('hseFrame.item.waive', { defaultValue: 'Waive' })}
            </Button>
          )}
          {!open && (
            <Button size="sm" variant="ghost" onClick={() => write.send(() => reopenItem(projectId, item.id))}>
              {t('hseFrame.item.reopen', { defaultValue: 'Reopen' })}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setPanel(panel === 'link' ? 'none' : 'link')}>
            {t('hseFrame.item.link', { defaultValue: 'Link a record' })}
          </Button>
          {item.source === 'manual' && (
            <Button size="sm" variant="ghost" onClick={() => onRemove({ name: item.title, run: () => deleteItem(projectId, item.id) })}>
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          )}
        </div>
      )}
      {panel === 'meet' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Input label={t('hseFrame.item.met_on', { defaultValue: 'Met on' })} type="date" max={localToday()} value={day} onChange={(e) => setDay(e.target.value)} />
          <Input label={t('hseFrame.item.evidence', { defaultValue: 'Evidence note' })} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button size="sm" disabled={write.pending} onClick={() => write.send(() => meetItem(projectId, item.id, { met_on: day, evidence_note: note }), () => setPanel('none'))} data-testid="item-meet-confirm">
            {t('common.confirm', { defaultValue: 'Confirm' })}
          </Button>
        </div>
      )}
      {panel === 'waive' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Input label={t('hseFrame.item.reason', { defaultValue: 'Reason' })} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button size="sm" disabled={write.pending || note.trim().length < 3} onClick={() => write.send(() => waiveItem(projectId, item.id, { reason: note, not_applicable: false }), () => setPanel('none'))} data-testid="item-waive-confirm">
            {t('common.confirm', { defaultValue: 'Confirm' })}
          </Button>
          <Button size="sm" variant="ghost" disabled={write.pending || note.trim().length < 3} onClick={() => write.send(() => waiveItem(projectId, item.id, { reason: note, not_applicable: true }), () => setPanel('none'))}>
            {t('hseFrame.item.not_applicable', { defaultValue: 'Not applicable' })}
          </Button>
        </div>
      )}
      {panel === 'link' && <LinkPicker projectId={projectId} item={item} catalogue={catalogue} write={write} />}
    </li>
  );
}

function AddItem({ projectId, catalogue, write }: { projectId: string; catalogue: Catalogue; write: HseWrite }) {
  const { t, i18n } = useTranslation();
  const topics = catalogue.topics.filter((x) => x.basis === 'items');
  const [topic, setTopic] = useState(topics[0]?.code ?? '');
  const [title, setTitle] = useState('');
  const [party, setParty] = useState('');
  const [due, setDue] = useState('');
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border-light p-3" data-testid="add-item">
      <label className="flex flex-col gap-1 text-xs text-content-secondary">
        {t('hseFrame.add.topic', { defaultValue: 'Topic' })}
        <select className="h-10 rounded-lg border border-border bg-surface-primary px-2 text-sm" value={topic} onChange={(e) => setTopic(e.target.value)} data-testid="add-topic">
          {topics.map((x) => (
            <option key={x.code} value={x.code}>
              {labelOf(x, i18n.language)}
            </option>
          ))}
        </select>
      </label>
      <Input label={t('hseFrame.add.title', { defaultValue: 'Requirement' })} value={title} onChange={(e) => setTitle(e.target.value)} data-testid="add-title" />
      <Input label={t('hseFrame.add.party', { defaultValue: 'Responsible' })} value={party} onChange={(e) => setParty(e.target.value)} />
      <Input label={t('hseFrame.add.due', { defaultValue: 'Due' })} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      <Button
        size="sm"
        icon={<Plus size={14} />}
        disabled={!title.trim() || !topic || write.pending}
        onClick={() =>
          write.send(() => createItem(projectId, { topic, title: title.trim(), responsible_party: party, due_date: due || null }), () => {
            setTitle('');
            setParty('');
            setDue('');
          })
        }
        data-testid="add-submit"
      >
        {t('hseFrame.add.submit', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

export function RegisterPanel(props: Props) {
  const { t, i18n } = useTranslation();
  const [removing, setRemoving] = useState<RemoveTarget | null>(null);
  const topics = props.catalogue.topics.filter((x) => x.basis !== 'roles');
  const groups = groupByTopic(props.items, topics.map((x) => x.code));
  return (
    <div className="space-y-5" data-testid="register-panel">
      <div className="flex justify-end">
        <ExportButtons projectId={props.projectId} what="register" />
      </div>
      {groups.map(([code, rows]) => {
        const topic = props.catalogue.topics.find((x) => x.code === code);
        const p = progress(rows);
        return (
          <section key={code} data-testid={`topic-${code}`}>
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-content-primary">{labelOf(topic, i18n.language, code)}</h2>
              {p.total > 0 && (
                <span className="text-xs text-content-secondary">
                  {t('hseFrame.register.progress', { defaultValue: '{{done}} of {{total}} mandatory done', done: p.done, total: p.total })}
                </span>
              )}
            </div>
            {rows.length === 0 ? (
              <p className="text-sm text-content-tertiary">{t('hseFrame.register.empty', { defaultValue: 'Nothing recorded for this topic yet.' })}</p>
            ) : (
              <ul className="space-y-2">
                {rows.map((item) => (
                  <ItemRow key={item.id} {...props} item={item} onRemove={setRemoving} />
                ))}
              </ul>
            )}
          </section>
        );
      })}
      {props.canEdit && <AddItem projectId={props.projectId} catalogue={props.catalogue} write={props.write} />}
      <RemoveConfirm target={removing} write={props.write} onClose={() => setRemoving(null)} />
    </div>
  );
}
