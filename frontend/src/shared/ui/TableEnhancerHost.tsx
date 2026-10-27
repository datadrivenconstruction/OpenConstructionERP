// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Mounts the table enhancer once, feeds it translated labels, and shows the
 * keyboard-mode hint strip and the copy confirmation.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { setEnhancerLabels, startTableEnhancer } from '@/shared/lib/tableEnhancer';
import { TABLE_PREFS_EVENT, readTablePrefs } from '@/shared/lib/tablePrefs';
import { useToastStore } from '@/stores/useToastStore';
import { ListViewsPanel } from './ListViewsPanel';

export function TableEnhancerHost() {
  const { t } = useTranslation();
  const [keyboard, setKeyboard] = useState(() => readTablePrefs().keyboard);
  const [excel, setExcel] = useState(() => readTablePrefs().excel);

  useEffect(() => {
    setEnhancerLabels({
      total: t('tables.total', { defaultValue: 'Total' }),
      filter: t('tables.filter', { defaultValue: 'Filter' }),
      filterPlaceholder: t('tables.filter_placeholder', { defaultValue: 'Contains...' }),
      copied: (count) => t('tables.copied', { defaultValue: 'Cells copied: {{count}}', count }),
    });
  }, [t]);

  useEffect(() => {
    const stop = startTableEnhancer();
    const onPrefs = () => {
      const p = readTablePrefs();
      setKeyboard(p.keyboard);
      setExcel(p.excel);
    };
    const onCopied = (e: Event) =>
      useToastStore.getState().addToast({ type: 'success', title: String((e as CustomEvent).detail) });
    window.addEventListener(TABLE_PREFS_EVENT, onPrefs);
    window.addEventListener('oe:table-copied', onCopied);
    return () => {
      stop();
      window.removeEventListener(TABLE_PREFS_EVENT, onPrefs);
      window.removeEventListener('oe:table-copied', onCopied);
    };
  }, []);

  return (
    <>
      {excel && <ListViewsPanel />}
      {keyboard && (
    <div className="oe-shortcut-strip" role="note" data-no-print>
      <span><kbd>Ctrl</kbd>+<kbd>K</kbd> {t('tables.hint_commands', { defaultValue: 'Commands' })}</span>
      <span><kbd>↑</kbd><kbd>↓</kbd><kbd>←</kbd><kbd>→</kbd> {t('tables.hint_move', { defaultValue: 'Move' })}</span>
      <span><kbd>Enter</kbd> {t('tables.hint_open', { defaultValue: 'Open' })}</span>
      <span><kbd>Ctrl</kbd>+<kbd>C</kbd> {t('tables.hint_copy', { defaultValue: 'Copy' })}</span>
      <span><kbd>?</kbd> {t('tables.hint_all', { defaultValue: 'All shortcuts' })}</span>
    </div>
      )}
    </>
  );
}
