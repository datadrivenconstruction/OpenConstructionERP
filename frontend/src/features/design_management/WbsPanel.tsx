// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The work breakdown of the project as an indented list. Changing a code
// shows the new codes of everything below it before anything is saved. A
// node that records refer to is closed, not deleted, and references that
// match no node are listed so they can be corrected.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ListTree } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';

import {
  closeWbsNode,
  createWbsNode,
  deleteWbsNode,
  designKeys,
  listUnresolvedWbs,
  previewWbsRenumber,
  updateWbsNode,
  type WbsInput,
  type WbsNode,
} from './api';
import { CELL, CELL_MUTED, InlineQueryState, PanelHeader, Table, ToneBadge, type DesignContext, WriteButton } from './DesignBits';
import { FormDialog, str, type FieldSpec, type FormValues } from './FormDialog';
import { useDesignAction, useDesignList } from './hooks';
import { WBS_KIND, humanizeCode, ui, uiCount, vocab, vocabOptions, type TFn } from './labels';
import { changedFields, filledFields, wbsRows } from './rules';

type Dialog = { kind: 'create'; parentId: string } | { kind: 'edit'; node: WbsNode } | { kind: 'delete'; node: WbsNode } | null;

function nodeValues(node: WbsNode | null, parentId = ''): FormValues {
  return {
    code: node?.code ?? '',
    name: node?.name ?? '',
    parent_id: node?.parent_id ?? parentId,
    kind: node?.kind ?? 'package',
    discipline: node?.discipline ?? '',
  };
}

/** The new codes a code change gives the nodes below, asked from the server while the dialog is open. */
function RenumberPreview({ projectId, node, code }: { projectId: string; node: WbsNode; code: string }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const wanted = code.trim();
  const preview = useQuery({
    queryKey: [...designKeys.list(projectId, 'wbs-renumber'), node.id, wanted],
    queryFn: () => previewWbsRenumber(projectId, node.id, wanted),
    enabled: !!wanted && wanted !== node.code,
    retry: false,
  });
  const rows = (preview.data ?? []).filter((r) => r.id !== node.id);
  if (!wanted || wanted === node.code) return null;
  if (preview.isLoading || preview.isError) return <InlineQueryState query={preview} />;
  if (rows.length === 0) return null;
  return (
    <div className="rounded-md bg-surface-secondary p-2 text-xs text-content-secondary" data-testid="wbs-renumber-preview">
      <p className="font-medium text-content-primary">{uiCount(t, 'design.ui.wbs.renumber_title', rows.length)}</p>
      <ul className="mt-1 space-y-0.5 font-mono">
        {rows.map((r) => (
          <li key={r.id}>
            {r.old} → {r.new}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function WbsPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const action = useDesignAction(ctx.onChanged);
  const unresolved = useDesignList(ctx.projectId, 'wbs-unresolved', listUnresolvedWbs);
  const rows = useMemo(() => wbsRows(ctx.wbs), [ctx.wbs]);

  const fields = (editing: WbsNode | null): FieldSpec[] => [
    {
      name: 'code',
      label: ui(t, 'design.ui.field.code'),
      type: 'text',
      required: true,
      hint: ctx.setup.hierarchical_codes ? ui(t, 'design.ui.wbs.code_hint', { separator: ctx.setup.wbs_separator }) : undefined,
    },
    { name: 'name', label: ui(t, 'design.ui.field.name'), type: 'text' },
    {
      name: 'parent_id',
      label: ui(t, 'design.ui.wbs.parent'),
      type: 'select',
      options: ctx.wbs
        .filter((n) => n.id !== editing?.id)
        .map((n) => ({ value: n.id, label: n.name ? `${n.code} ${n.name}` : n.code })),
    },
    { name: 'kind', label: ui(t, 'design.ui.wbs.kind'), type: 'select', required: true, options: vocabOptions(t, WBS_KIND) },
    { name: 'discipline', label: ui(t, 'design.ui.field.discipline'), type: 'text' },
  ];

  return (
    <div className="space-y-4" data-testid="design-wbs-panel">
      <PanelHeader
        title={ui(t, 'design.ui.wbs.title')}
        hint={ui(t, 'design.ui.wbs.hint')}
        action={
          <WriteButton onClick={() => setDialog({ kind: 'create', parentId: '' })} data-testid="wbs-add">
            {ui(t, 'design.ui.wbs.add')}
          </WriteButton>
        }
      />

      {(unresolved.isError || unresolved.isLoading) && <InlineQueryState query={unresolved} />}
      {(unresolved.data ?? []).length > 0 && (
        <div role="status" className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm" data-testid="wbs-unresolved">
          <p className="flex items-center gap-2 font-medium text-content-primary">
            <AlertTriangle size={14} aria-hidden />
            {uiCount(t, 'design.ui.wbs.unresolved_title', (unresolved.data ?? []).length)}
          </p>
          <ul className="ml-6 mt-1 list-disc text-xs text-content-secondary">
            {(unresolved.data ?? []).slice(0, 20).map((ref) => (
              <li key={`${ref.table}-${ref.row_id}`}>
                {ui(t, 'design.ui.wbs.unresolved_row', { module: humanizeCode(ref.module), value: ref.value })}
              </li>
            ))}
          </ul>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<ListTree size={28} />}
          title={ui(t, 'design.ui.wbs.empty_title')}
          description={ui(t, 'design.ui.wbs.empty_body')}
          action={{ label: ui(t, 'design.ui.wbs.add'), onClick: () => setDialog({ kind: 'create', parentId: '' }) }}
        />
      ) : (
        <Table
          testId="wbs-table"
          head={[
            ui(t, 'design.ui.field.code'),
            ui(t, 'design.ui.field.name'),
            ui(t, 'design.ui.wbs.kind'),
            ui(t, 'design.ui.wbs.used_by'),
            '',
          ]}
        >
          {rows.map(({ node, depth, referenceCount }) => (
            <tr key={node.id} data-testid="wbs-row">
              <td className={`${CELL} font-mono`} style={{ paddingInlineStart: `${0.75 + depth * 1.25}rem` }}>
                {node.code}
              </td>
              <td className={CELL}>
                {node.name}
                {node.closed && (
                  <span className="ml-2">
                    <ToneBadge tone="neutral">{ui(t, 'design.ui.wbs.closed')}</ToneBadge>
                  </span>
                )}
                {node.duplicate_code && (
                  <span className="ml-2">
                    <ToneBadge tone="error" testId="wbs-duplicate">
                      {ui(t, 'design.ui.wbs.duplicate')}
                    </ToneBadge>
                  </span>
                )}
              </td>
              <td className={CELL_MUTED}>{vocab(t, WBS_KIND, node.kind)}</td>
              <td className={CELL_MUTED}>
                {referenceCount > 0 ? uiCount(t, 'design.ui.wbs.references', referenceCount) : ui(t, 'design.ui.wbs.unused')}
              </td>
              <td className={`${CELL} whitespace-nowrap text-right`}>
                <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'create', parentId: node.id })}>
                  {ui(t, 'design.ui.wbs.add_below')}
                </WriteButton>
                <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'edit', node })}>
                  {ui(t, 'design.ui.action.edit')}
                </WriteButton>
                <WriteButton
                  size="sm"
                  variant="ghost"
                  disabled={action.pending}
                  onClick={() => action.run(() => closeWbsNode(ctx.projectId, node.id, !node.closed))}
                >
                  {node.closed ? ui(t, 'design.ui.wbs.reopen') : ui(t, 'design.ui.wbs.close')}
                </WriteButton>
                <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'delete', node })}>
                  {ui(t, 'design.ui.action.delete')}
                </WriteButton>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {dialog?.kind === 'create' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.wbs.add')}
          fields={fields(null)}
          initial={nodeValues(null, dialog.parentId)}
          submitLabel={ui(t, 'design.ui.wbs.add')}
          submit={(values) => createWbsNode(ctx.projectId, filledFields<WbsInput>(values))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'edit' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.wbs.edit')}
          fields={fields(dialog.node)}
          initial={nodeValues(dialog.node)}
          submitLabel={ui(t, 'design.ui.action.save')}
          submit={(values) =>
            updateWbsNode(ctx.projectId, dialog.node.id, changedFields<WbsInput>(nodeValues(dialog.node), values, ['parent_id', 'discipline']))
          }
          extra={(values) => <RenumberPreview projectId={ctx.projectId} node={dialog.node} code={str(values, 'code')} />}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'delete' && (
        <FormDialog
          projectId={ctx.projectId}
          danger
          title={ui(t, 'design.ui.wbs.delete_title')}
          subtitle={ui(t, 'design.ui.wbs.delete_body', { code: dialog.node.code })}
          fields={[]}
          initial={{}}
          submitLabel={ui(t, 'design.ui.action.delete')}
          submit={() => deleteWbsNode(ctx.projectId, dialog.node.id)}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
    </div>
  );
}
