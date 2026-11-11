import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import {
  BOARD_PRINT_CSS,
  BOARD_PRINT_ID,
  BoardPhoneCell,
  BoardPrintButton,
  dialNumber,
  smsHref,
  telHref,
} from '../boardContact';

afterEach(() => vi.restoreAllMocks());

describe('<BoardPrintButton>', () => {
  it('opens the print dialog', () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => {});
    render(<BoardPrintButton />);
    fireEvent.click(screen.getByTestId('board-print'));
    expect(print).toHaveBeenCalledTimes(1);
  });

  it('prints only the board, in landscape', () => {
    expect(BOARD_PRINT_CSS).toContain('@media print');
    expect(BOARD_PRINT_CSS).toContain('size: landscape');
    expect(BOARD_PRINT_CSS).toContain(`#${BOARD_PRINT_ID}`);
    expect(BOARD_PRINT_CSS).toContain('visibility: hidden');
  });
});

describe('phone links', () => {
  it('keeps digits and a leading plus for the dialler', () => {
    expect(dialNumber(' +49 (170) 123-4567 ')).toBe('+491701234567');
    expect(dialNumber('0170 1234567')).toBe('01701234567');
    expect(telHref('+49 170 1234567')).toBe('tel:+491701234567');
  });

  it('prefills the sms body, encoded', () => {
    expect(smsHref('+49 170 1234567', 'Max, Tower & Co from 11/11/2026')).toBe(
      'sms:+491701234567?body=Max%2C%20Tower%20%26%20Co%20from%2011%2F11%2F2026',
    );
  });

  it('renders tel and sms links for a resource with a phone', () => {
    render(<BoardPhoneCell phone="+49 170 1234567" smsBody="On site Monday" />);
    expect(screen.getByTestId('board-phone-tel').getAttribute('href')).toBe('tel:+491701234567');
    expect(screen.getByTestId('board-phone-sms').getAttribute('href')).toBe(
      'sms:+491701234567?body=On%20site%20Monday',
    );
  });

  it('renders no links when there is no phone', () => {
    render(<BoardPhoneCell phone={null} smsBody="x" />);
    expect(screen.queryByTestId('board-phone-tel')).toBeNull();
    expect(screen.queryByTestId('board-phone-sms')).toBeNull();
  });
});
