// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The design take-off writes neutral codes into the BOQ, tender packages, RFQs and addenda; every page that shows
// such a record reads it through one formatter, in the reader's language, and older free-text rows stay readable.
import { describe, expect, it } from 'vitest';
import i18next from 'i18next';

import de from '@/app/locales/de';
import en from '@/app/locales/en';
import { designRecordName, designRecordText } from '../designRecordName';

async function tFor(lng: 'en' | 'de') {
  const inst = i18next.createInstance();
  await inst.init({ lng, resources: { en: { translation: en.translation }, de: { translation: de.translation } } });
  return inst.t.bind(inst);
}

describe('designRecordName', () => {
  it('renders a take-off package code in English and German', async () => {
    expect(designRecordName(await tFor('en'), 'design_takeoff:IfcWall')).toContain('IfcWall');
    expect(designRecordName(await tFor('en'), 'design_takeoff:IfcWall')).not.toContain('design_takeoff');
    expect(designRecordName(await tFor('de'), 'design_takeoff:IfcWall')).toBe(
      String((await tFor('de'))('design.takeoff.package_name', { ifc_class: 'IfcWall' })),
    );
  });

  it('renders the take-off bill code', async () => {
    const t = await tFor('en');
    expect(designRecordName(t, 'design_takeoff')).toBe(String(t('design.takeoff.boq_name')));
    expect(designRecordName(t, 'design_takeoff')).not.toBe('design_takeoff');
  });

  it('renders an addendum title code with its revision number', async () => {
    expect(designRecordName(await tFor('en'), 'design_revision_quantities:3')).toBe(
      'Design revision 3: quantity changes',
    );
    expect(designRecordName(await tFor('de'), 'design_revision_quantities:3')).toBe(
      'Planungsrevision 3: Mengenänderungen',
    );
  });

  it('renders a change order title code, keeping the revision message a person typed', async () => {
    expect(designRecordName(await tFor('en'), 'design_revision:2')).toBe('Design revision 2');
    expect(designRecordName(await tFor('de'), 'design_revision:2:Fassade neu')).toBe('Planungsrevision 2: Fassade neu');
  });

  it('renders change order description tokens and leaves older English text alone', async () => {
    const de = await tFor('de');
    const text = '[co:elements|{"added": 1, "changed": 4, "removed": 2}]\n[co:no_estimate]';
    expect(designRecordText(de, text)).toBe(
      'Elemente: 1 hinzugefügt, 2 entfernt, 4 geändert.\nDas Projekt hat keine Planungskalkulation: Es wurde kein Kostenunterschied berechnet.',
    );
    expect(designRecordText(await tFor('en'), 'Walls [co:item_unpriced]')).toBe('Walls (no rate: amount not costed)');
    expect(designRecordText(de, 'Accepted design revision R2.')).toBe('Accepted design revision R2.');
    expect(designRecordText(de, null)).toBe('');
  });

  it('renders the estimate-row token and the design estimate bill name', async () => {
    const de = await tFor('de');
    expect(designRecordText(await tFor('en'), '[co:in_estimate|{"code": "CO-007", "number": 3}]')).toBe(
      'CO-007: already in this estimate through design revision R3',
    );
    expect(designRecordText(de, '[co:in_estimate|{"code": "CO-007", "number": 3}]')).toBe(
      'CO-007: bereits in dieser Kalkulation durch Planungsrevision R3',
    );
    expect(designRecordName(de, 'design_estimate')).toBe('Planungskalkulation');
  });

  it('leaves names a person typed, and old English addendum titles, as they are', async () => {
    const t = await tFor('de');
    expect(designRecordName(t, 'Design revision 2: quantity changes')).toBe('Design revision 2: quantity changes');
    expect(designRecordName(t, 'Rohbau Los 1')).toBe('Rohbau Los 1');
    expect(designRecordName(t, null)).toBe('');
  });
});
