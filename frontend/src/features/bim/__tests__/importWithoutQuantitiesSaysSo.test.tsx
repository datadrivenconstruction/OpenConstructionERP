// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Without the DDC converter an IFC upload imports its elements with empty
// quantities and the backend stores the model as `degraded` with a reason code.
// The dock reported that as a plain success and the viewer said nothing. Both
// now show a translated warning keyed by the code.
//
// The test setup's i18n mock renders each label's English defaultValue.

import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import {
  BIM_QUANTITY_WARNING_CODES,
  bimQuantityWarningCode,
  bimQuantityWarningText,
} from '@/shared/lib/bimQuantityWarning';
import { QuantityWarningBanner } from '../QuantityWarningBanner';
import en from '@/app/locales/en';
import de from '@/app/locales/de';

afterEach(() => cleanup());

describe('bimQuantityWarningCode', () => {
  it('warns only for a degraded model', () => {
    expect(bimQuantityWarningCode({ status: 'ready', error_code: 'converter_absent' })).toBeNull();
    expect(bimQuantityWarningCode({ status: 'error', error_code: 'no_quantities' })).toBeNull();
    expect(bimQuantityWarningCode(null)).toBeNull();
  });

  it('reads the lifted code first, then the metadata', () => {
    expect(bimQuantityWarningCode({ status: 'degraded', error_code: 'no_quantities' })).toBe('no_quantities');
    expect(
      bimQuantityWarningCode({ status: 'degraded', metadata: { error_code: 'converter_absent' } }),
    ).toBe('converter_absent');
  });

  it('still warns, as the converter case, when the code is unknown', () => {
    expect(bimQuantityWarningCode({ status: 'degraded', error_code: 'something_new' })).toBe(
      'no_quantities_converter_absent',
    );
  });

  it('has an English and a German text for every code', () => {
    const enMap = en.translation;
    const deMap = de.translation;
    for (const code of BIM_QUANTITY_WARNING_CODES) {
      const { key, defaultValue } = bimQuantityWarningText(code);
      expect(enMap[key]).toBe(defaultValue);
      expect(deMap[key]).toBeTruthy();
      expect(deMap[key]).not.toBe(defaultValue);
    }
  });
});

describe('QuantityWarningBanner', () => {
  it('names the missing converter on a degraded model', () => {
    render(
      <QuantityWarningBanner
        model={{ id: 'm-1', status: 'degraded', error_code: 'no_quantities_converter_absent' }}
      />,
    );
    const banner = screen.getByTestId('bim-quantity-warning');
    expect(banner).toHaveTextContent('Imported without quantities');
    expect(banner).toHaveTextContent('the DDC converter is not available on this server');
  });

  it('stays away from a ready model', () => {
    render(<QuantityWarningBanner model={{ id: 'm-1', status: 'ready' }} />);
    expect(screen.queryByTestId('bim-quantity-warning')).toBeNull();
  });

  it('can be dismissed', () => {
    render(<QuantityWarningBanner model={{ id: 'm-1', status: 'degraded', error_code: 'no_quantities' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('bim-quantity-warning')).toBeNull();
  });
});
