// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The note beside a country default is read in the reader's language.
//
// The server sends each figure's note as an English sentence. Put straight
// into the tooltip, a German reader hovering "Standard für Deutschland" got
// English. The note now goes through `contracts.country_defaults.<CC>.<field>.note`
// with the server's English only as the fallback. The reference beside it (a
// clause, a law) is data and stays as written.
//
// Rendered through a real i18next instance in German with no English behind
// it, because an English fallback in the store is exactly what would hide a
// note that never went through a key.

import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import i18next, { type i18n as I18n } from 'i18next';
import type { ReactElement } from 'react';

vi.unmock('react-i18next');

import { I18nextProvider } from 'react-i18next';
import { DefaultHint } from './ContractPaymentTerms';
import type { CountryDefaultSource } from './api';

const GERMAN_NOTE = 'Abschlagszahlungen werden binnen 21 Tagen nach Zugang der Aufstellung fällig.';
const GERMAN_CAP_NOTE = 'Der Einbehalt endet an der in den Contract Data genannten Grenze.';
const GERMAN_US_RATE_NOTE = 'Zehn Prozent, die auf fünf sinken, sind das übliche Muster.';
const GERMAN_CEILING_NOTE = 'Durch das Recht von {{subdivision}} auf {{percent}} Prozent gesenkt, ab {{since}}.';

let i18n: I18n;

beforeAll(async () => {
  i18n = i18next.createInstance();
  await i18n.init({
    lng: 'de',
    fallbackLng: false,
    resources: {
      de: {
        translation: {
          'contracts.country_defaults.DE.payment_period_days.note': GERMAN_NOTE,
          'contracts.country_defaults.AE.retention_cap_percent.note': GERMAN_CAP_NOTE,
          'contracts.country_defaults.US.retention_percent.note': GERMAN_US_RATE_NOTE,
          'contracts.statutory_ceiling.retention_percent.note': GERMAN_CEILING_NOTE,
        },
      },
    },
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
});

afterEach(() => cleanup());

function renderHint(ui: ReactElement) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

const dePeriod: CountryDefaultSource = {
  source: 'standard_form',
  reference: '§ 16 Abs. 1 Nr. 3 VOB/B',
  note: 'Interim payments fall due within 21 days of the client receiving the statement of work.',
};

describe('DefaultHint note', () => {
  it("shows the note in the reader's language, not the server's English", () => {
    renderHint(<DefaultHint field="payment_period_days" country="DE" source={dePeriod} />);
    const title = screen.getByTestId('default-hint-payment_period_days').getAttribute('title') ?? '';
    expect(title).toContain(GERMAN_NOTE);
    expect(title).not.toContain(dePeriod.note);
    // The reference is data and is shown as written.
    expect(title).toContain('§ 16 Abs. 1 Nr. 3 VOB/B');
  });

  it("falls back to the server's English where the locale has no note yet", () => {
    const frPeriod: CountryDefaultSource = {
      source: 'statute',
      reference: 'Code de la commande publique, art. R2192-10',
      note: 'Public works are paid within 30 days.',
    };
    renderHint(<DefaultHint field="payment_period_days" country="FR" source={frPeriod} />);
    const title = screen.getByTestId('default-hint-payment_period_days').getAttribute('title') ?? '';
    expect(title).toContain('Public works are paid within 30 days.');
  });

  it('explains a rate held to the cap with the note of the cap', () => {
    const aeCap: CountryDefaultSource = {
      source: 'standard_form',
      reference: 'FIDIC Red Book 2017, Sub-Clause 14.3(iii), Limit of Retention Money',
      note: 'Retention stops at the limit stated in the Contract Data.',
    };
    renderHint(
      <DefaultHint
        field="retention_percent"
        noteField="retention_cap_percent"
        country="AE"
        source={aeCap}
      />,
    );
    const title = screen.getByTestId('default-hint-retention_percent').getAttribute('title') ?? '';
    expect(title).toContain(GERMAN_CAP_NOTE);
    expect(title).not.toContain(aeCap.note);
  });

  it("explains a rate lowered to a state ceiling with the ceiling's note, not the country's", () => {
    // The rate is the state's, so the country's own note (ten percent stepping
    // down) beside a five would contradict the figure it explains.
    const ceiling: CountryDefaultSource = {
      source: 'statute',
      reference: 'California Civil Code § 8811; California Public Contract Code § 7201',
      note: 'Lowered to 5 percent by the law of California.',
      note_key: 'contracts.statutory_ceiling.retention_percent.note',
      note_params: { percent: '5', subdivision: 'California', since: '2026-01-01' },
    };
    renderHint(<DefaultHint field="retention_percent" country="US" source={ceiling} />);
    const title = screen.getByTestId('default-hint-retention_percent').getAttribute('title') ?? '';
    expect(title).toContain('Durch das Recht von California auf 5 Prozent gesenkt, ab 2026-01-01.');
    expect(title).not.toContain(GERMAN_US_RATE_NOTE);
    expect(title).not.toContain(ceiling.note);
  });

  it('adds no note where the source states none', () => {
    renderHint(
      <DefaultHint
        field="payment_period_days"
        country="DE"
        source={{ ...dePeriod, note: '' }}
      />,
    );
    const title = screen.getByTestId('default-hint-payment_period_days').getAttribute('title') ?? '';
    expect(title).not.toContain(GERMAN_NOTE);
  });
});
