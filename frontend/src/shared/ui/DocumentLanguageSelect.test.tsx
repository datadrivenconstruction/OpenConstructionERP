// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The document-language choice is one searchable list of every language a
// document exists in, each under its own name, wherever a screen asks for one.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

import { DocumentLanguageSelect } from './DocumentLanguageSelect';
import { MESSAGE_DOCUMENT_LOCALES, PROPERTY_DOCUMENT_LOCALES } from '@/shared/lib/documentExport';

Element.prototype.scrollIntoView = vi.fn();

afterEach(cleanup);

describe('DocumentLanguageSelect', () => {
  it('lists every language it is given under its own name and searches by English name', () => {
    const onChange = vi.fn();
    render(<DocumentLanguageSelect value="en" onChange={onChange} locales={PROPERTY_DOCUMENT_LOCALES} data-testid="lang" />);
    fireEvent.click(screen.getByTestId('lang'));
    expect(screen.getAllByRole('option')).toHaveLength(PROPERTY_DOCUMENT_LOCALES.length);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hebrew' } });
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(1);
    fireEvent.click(options[0]!);
    expect(onChange).toHaveBeenCalledWith('he');
  });

  it('offers the property documents in the register languages plus Mongolian', () => {
    expect(PROPERTY_DOCUMENT_LOCALES).toContain('mn');
    expect(PROPERTY_DOCUMENT_LOCALES).toContain('uk');
    expect(PROPERTY_DOCUMENT_LOCALES).toContain('he');
    expect(new Set(PROPERTY_DOCUMENT_LOCALES).size).toBe(PROPERTY_DOCUMENT_LOCALES.length);
  });

  it('offers messages and workbooks in every backend language, Bengali included', () => {
    expect(MESSAGE_DOCUMENT_LOCALES).toContain('bn');
    expect(MESSAGE_DOCUMENT_LOCALES).toHaveLength(38);
  });
});
