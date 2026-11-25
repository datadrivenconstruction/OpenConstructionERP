// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Pencil, RefreshCw, Trash2, X } from 'lucide-react';
import clsx from 'clsx';
import {
  MAX_LAYOUTS,
  MAX_LAYOUT_NAME,
  layoutMatches,
  type LayoutNameError,
  type SidebarLayoutData,
} from './sidebarLayouts';
import { useSidebarLayoutsStore, type LayoutResult } from './useSidebarLayoutsStore';

interface Props {
  /** The arrangement as it is right now, including unsaved Edit-menu changes. */
  current: SidebarLayoutData;
  /** Switch the sidebar to a saved layout. */
  onApply: (data: SidebarLayoutData) => void;
}

const iconBtn =
  'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors';

/** Save, switch, rename and delete named sidebar layouts, inside the Edit menu. */
export function SidebarLayoutsPanel({ current, onApply }: Props) {
  const { t } = useTranslation();
  const layouts = useSidebarLayoutsStore((s) => s.layouts);
  const loaded = useSidebarLayoutsStore((s) => s.loaded);
  const load = useSidebarLayoutsStore((s) => s.load);
  const save = useSidebarLayoutsStore((s) => s.save);
  const rename = useSidebarLayoutsStore((s) => s.rename);
  const update = useSidebarLayoutsStore((s) => s.update);
  const remove = useSidebarLayoutsStore((s) => s.remove);

  const bodyId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<LayoutNameError | 'save_failed' | null>(null);

  useEffect(() => {
    if (!loaded) void load();
  }, [loaded, load]);

  const errorText = (code: LayoutNameError | 'save_failed'): string => {
    switch (code) {
      case 'empty':
        return t('sidebar.layouts_error_empty', { defaultValue: 'Enter a name for the layout' });
      case 'too_long':
        return t('sidebar.layouts_error_too_long', {
          defaultValue: 'Use at most {{max}} characters',
          max: MAX_LAYOUT_NAME,
        });
      case 'taken':
        return t('sidebar.layouts_error_taken', { defaultValue: 'You already have a layout with this name' });
      case 'limit':
        return t('sidebar.layouts_error_limit', {
          defaultValue: 'You can keep at most {{max}} layouts. Delete one first',
          max: MAX_LAYOUTS,
        });
      default:
        return t('sidebar.layouts_error_save', { defaultValue: 'Could not save. Try again' });
    }
  };

  const finish = (result: LayoutResult, done: () => void) => {
    if (result.ok) {
      setError(null);
      done();
    } else {
      setError(result.error);
    }
  };

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    finish(await save(name, current), () => setName(''));
  };

  const onRename = async (e: FormEvent, id: string) => {
    e.preventDefault();
    finish(await rename(id, renameValue), () => setRenameId(null));
  };

  return (
    <div className="mt-2.5 rounded-lg border border-border-light bg-surface-secondary/30" data-testid="sidebar-layouts">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-content-primary"
      >
        <span className="flex-1 text-start">{t('sidebar.layouts_title', { defaultValue: 'My layouts' })}</span>
        <span className="tabular-nums text-2xs text-content-tertiary">
          {t('sidebar.layouts_count', {
            defaultValue: '{{count}} of {{max}}',
            count: layouts.length,
            max: MAX_LAYOUTS,
          })}
        </span>
        <ChevronDown size={12} className={clsx('transition-transform', open && 'rotate-180')} aria-hidden />
      </button>

      {open && (
        <div id={bodyId} className="space-y-1.5 border-t border-border-light px-2 py-2">
          {layouts.length === 0 ? (
            <p className="px-1 text-2xs text-content-tertiary">
              {t('sidebar.layouts_empty', {
                defaultValue: 'Arrange the menu, then save it under a name to come back to it later.',
              })}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {layouts.map((layout) => {
                const active = layoutMatches(layout.data, current);
                if (renameId === layout.id) {
                  return (
                    <li key={layout.id}>
                      <form onSubmit={(e) => onRename(e, layout.id)} className="flex items-center gap-1">
                        <input
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          maxLength={MAX_LAYOUT_NAME}
                          autoFocus
                          aria-label={t('sidebar.layouts_rename', {
                            defaultValue: 'Rename "{{name}}"',
                            name: layout.name,
                          })}
                          className="oe-input oe-input-sm min-w-0 flex-1"
                        />
                        <button
                          type="submit"
                          className={iconBtn}
                          aria-label={t('sidebar.layouts_rename_confirm', { defaultValue: 'Save name' })}
                        >
                          <Check size={14} />
                        </button>
                        <button
                          type="button"
                          className={iconBtn}
                          onClick={() => {
                            setRenameId(null);
                            setError(null);
                          }}
                          aria-label={t('sidebar.cancel', { defaultValue: 'Cancel' })}
                        >
                          <X size={14} />
                        </button>
                      </form>
                    </li>
                  );
                }
                if (deleteId === layout.id) {
                  return (
                    <li key={layout.id} className="flex items-center gap-1 px-1 text-2xs text-content-secondary">
                      <span className="min-w-0 flex-1 truncate">
                        {t('sidebar.layouts_delete_confirm', {
                          defaultValue: 'Delete "{{name}}"?',
                          name: layout.name,
                        })}
                      </span>
                      <button
                        type="button"
                        className={clsx(iconBtn, 'text-semantic-error')}
                        onClick={async () => finish(await remove(layout.id), () => setDeleteId(null))}
                        aria-label={t('sidebar.layouts_delete', { defaultValue: 'Delete layout' })}
                      >
                        <Check size={14} />
                      </button>
                      <button
                        type="button"
                        className={iconBtn}
                        onClick={() => setDeleteId(null)}
                        aria-label={t('sidebar.cancel', { defaultValue: 'Cancel' })}
                      >
                        <X size={14} />
                      </button>
                    </li>
                  );
                }
                return (
                  <li key={layout.id} className="flex items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => onApply(layout.data)}
                      aria-pressed={active}
                      title={layout.name}
                      className={clsx(
                        'min-w-0 flex-1 truncate rounded-md px-2 py-1 text-start text-xs transition-colors',
                        active
                          ? 'bg-oe-blue/10 font-medium text-oe-blue'
                          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                      )}
                    >
                      {layout.name}
                    </button>
                    <button
                      type="button"
                      className={iconBtn}
                      onClick={async () => finish(await update(layout.id, current), () => undefined)}
                      aria-label={t('sidebar.layouts_update', {
                        defaultValue: 'Replace "{{name}}" with the current menu',
                        name: layout.name,
                      })}
                    >
                      <RefreshCw size={12} />
                    </button>
                    <button
                      type="button"
                      className={iconBtn}
                      onClick={() => {
                        setRenameId(layout.id);
                        setRenameValue(layout.name);
                        setError(null);
                      }}
                      aria-label={t('sidebar.layouts_rename', {
                        defaultValue: 'Rename "{{name}}"',
                        name: layout.name,
                      })}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      type="button"
                      className={iconBtn}
                      onClick={() => setDeleteId(layout.id)}
                      aria-label={t('sidebar.layouts_delete_named', {
                        defaultValue: 'Delete "{{name}}"',
                        name: layout.name,
                      })}
                    >
                      <Trash2 size={12} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <form onSubmit={onSave} className="flex items-center gap-1">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={MAX_LAYOUT_NAME}
              aria-label={t('sidebar.layouts_name_label', { defaultValue: 'Layout name' })}
              placeholder={t('sidebar.layouts_name_placeholder', { defaultValue: 'Name this layout' })}
              className="oe-input oe-input-sm min-w-0 flex-1"
            />
            <button
              type="submit"
              className="shrink-0 rounded-lg border border-oe-blue/30 bg-oe-blue/10 px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue/15 transition-colors"
            >
              {t('sidebar.layouts_save_current', { defaultValue: 'Save current' })}
            </button>
          </form>
          {error && (
            <p role="alert" className="px-1 text-2xs text-semantic-error">
              {errorText(error)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
