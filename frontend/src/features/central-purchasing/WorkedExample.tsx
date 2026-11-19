// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The worked example on screen: three houses buy drywall together at 2 % off, and each
 * house still gets its own contract and its own budget check. Figures match the backend
 * test of the same example.
 */

import { useTranslation } from 'react-i18next';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';

const ROWS = [
  { name: 'House 1', qty: '5,200 + 2,000', net: '225988.00', budget: null },
  { name: 'House 2', qty: '2,800 + 1,000', net: '118580.00', budget: '112000.00' },
  { name: 'House 3', qty: '4,000 + 1,500', net: '172284.00', budget: null },
];

export function WorkedExample() {
  const { t } = useTranslation();
  return (
    <div className="space-y-2 text-sm">
      <p>
        {t('central_purchasing.example.body', {
          defaultValue:
            'Example: three houses need 12,000 m2 of partitions and 4,500 m2 of ceilings. One tender at 2 % off gives 516,852.00 for the group. Each house gets its own contract for its own share, booked on its own cost lines:',
        })}
      </p>
      <table className="w-full max-w-xl text-xs">
        <thead>
          <tr className="text-content-tertiary">
            <th scope="col" className="py-1 text-start font-medium">{t('central_purchasing.col.project', { defaultValue: 'Project' })}</th>
            <th scope="col" className="py-1 text-end font-medium">{t('central_purchasing.col.share_m2', { defaultValue: 'Share, m2' })}</th>
            <th scope="col" className="py-1 text-end font-medium">{t('central_purchasing.col.net', { defaultValue: 'Net' })}</th>
            <th scope="col" className="py-1 text-end font-medium">{t('central_purchasing.col.budget', { defaultValue: 'Budget' })}</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r, i) => (
            <tr key={r.name} className="border-t border-border-light">
              <td className="py-1">{t('central_purchasing.example.house', { defaultValue: 'House {{n}}', n: i + 1 })}</td>
              <td className="py-1 text-end tabular-nums"><bdi>{r.qty}</bdi></td>
              <td className="py-1 text-end tabular-nums"><MoneyDisplay amount={r.net} currency="EUR" /></td>
              <td className={`py-1 text-end tabular-nums ${r.budget ? 'text-semantic-warning' : ''}`}>
                {r.budget ? <MoneyDisplay amount={r.budget} currency="EUR" /> : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-content-secondary">
        {t('central_purchasing.example.outcome', {
          defaultValue:
            'House 2 is 6,580.00 over its budget, so it gets a warning before the award. Its team sees its own 118,580.00 and its contract, never the other houses.',
        })}
      </p>
    </div>
  );
}
