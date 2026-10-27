// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Tables" card in Settings > General: spreadsheet tables and keyboard mode, kept on this device. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { readTablePrefs, writeTablePrefs, type TablePrefs } from '@/shared/lib/tablePrefs';
import { Choice, OptionRow } from './AppearanceStyleCard';

export function TableOptionsCard() {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState<TablePrefs>(readTablePrefs);
  const update = (next: TablePrefs) => {
    writeTablePrefs(next);
    setPrefs(next);
  };
  const on = t('settings.tables_on', { defaultValue: 'On' });
  const off = t('settings.tables_off', { defaultValue: 'Off' });

  return (
    <Card>
      <CardHeader
        title={t('settings.tables_title', { defaultValue: 'Tables' })}
        subtitle={t('settings.tables_subtitle', {
          defaultValue: 'How lists and tables behave on every page.',
        })}
      />
      <CardContent>
        <div className="flex flex-col gap-3">
          <OptionRow label={t('settings.tables_excel', { defaultValue: 'Spreadsheet tables' })}>
            <Choice active={prefs.excel} onSelect={() => update({ ...prefs, excel: true })} label={on} />
            <Choice active={!prefs.excel} onSelect={() => update({ ...prefs, excel: false })} label={off} />
          </OptionRow>
          <p className="text-xs text-content-tertiary sm:ps-[9.5rem]">
            {t('settings.tables_excel_hint', {
              defaultValue:
                'Frozen header and first column, resizable columns, sort and filter in the header, a totals row, drag to select cells and Ctrl+C to paste into Excel.',
            })}
          </p>
          <OptionRow label={t('settings.tables_keyboard', { defaultValue: 'Keyboard mode' })}>
            <Choice active={prefs.keyboard} onSelect={() => update({ ...prefs, keyboard: true })} label={on} />
            <Choice active={!prefs.keyboard} onSelect={() => update({ ...prefs, keyboard: false })} label={off} />
          </OptionRow>
          <p className="text-xs text-content-tertiary sm:ps-[9.5rem]">
            {t('settings.tables_keyboard_hint', {
              defaultValue: 'Arrow keys and Enter move through tables, and shortcut hints stay on screen.',
            })}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
