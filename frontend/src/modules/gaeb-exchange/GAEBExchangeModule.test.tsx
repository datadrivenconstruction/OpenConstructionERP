// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  generateGAEBXML,
  type ExportPosition,
  type GAEBExportOptions,
} from './data/gaebExport';

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const samplePositions: ExportPosition[] = [
  {
    id: 'sec-1',
    ordinal: '01',
    description: 'Erdarbeiten',
    unit: '',
    quantity: 0,
    unitRate: 0,
    total: 0,
    isSection: true,
  },
  {
    id: 'pos-1',
    ordinal: '01.001',
    description: 'Baugrubenaushub, Boden DIN 18300 Kl.3-5, maschinell',
    unit: 'm3',
    quantity: 350.5,
    unitRate: 18.50,
    total: 6484.25,
    section: 'Erdarbeiten',
  },
  {
    id: 'pos-2',
    ordinal: '01.002',
    description: 'Bodenabtransport, inkl. Deponiegebühren',
    unit: 'm3',
    quantity: 420,
    unitRate: 24.00,
    total: 10080,
    section: 'Erdarbeiten',
  },
  {
    id: 'sec-2',
    ordinal: '02',
    description: 'Betonarbeiten',
    unit: '',
    quantity: 0,
    unitRate: 0,
    total: 0,
    isSection: true,
  },
  {
    id: 'pos-3',
    ordinal: '02.001',
    description: 'Stahlbeton C30/37 für Fundamente, inkl. Schalung',
    unit: 'm3',
    quantity: 85,
    unitRate: 380,
    total: 32300,
    section: 'Betonarbeiten',
  },
];

function makeOptions(overrides?: Partial<GAEBExportOptions>): GAEBExportOptions {
  return {
    format: 'X83',
    projectName: 'Testprojekt Berlin',
    boqName: 'Hauptangebot LV',
    currency: 'EUR',
    positions: samplePositions,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('generateGAEBXML', () => {
  it('generates valid XML structure with XML header', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(result.xml).toContain('<GAEB');
    expect(result.xml).toContain('</GAEB>');
  });

  it('includes GAEBInfo with version 3.3', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<Version>3.3</Version>');
    expect(result.xml).toContain('<ProgSystem>OpenEstimate</ProgSystem>');
  });

  it('includes project info', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<NamePrj>Testprojekt Berlin</NamePrj>');
    expect(result.xml).toContain('<Cur>EUR</Cur>');
  });

  it('generates X83 format with Award tag and prices', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X83' }));
    expect(result.xml).toContain('<Award>');
    expect(result.xml).toContain('</Award>');
    expect(result.xml).toContain('<UP>');
    expect(result.xml).toContain('<IT>');
  });

  it('generates X81 format with Tender tag and no prices', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X81' }));
    expect(result.xml).toContain('<Tender>');
    expect(result.xml).toContain('</Tender>');
    expect(result.xml).not.toContain('<UP>');
    expect(result.xml).not.toContain('<IT>');
  });

  it('exports correct number of positions and sections', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.positionCount).toBe(3); // 3 non-section positions
    expect(result.sectionCount).toBe(2);  // 2 sections
  });

  it('includes position descriptions', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('Baugrubenaushub');
    expect(result.xml).toContain('Stahlbeton C30/37');
  });

  it('includes quantities and units', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<Qty>350.500</Qty>');
    expect(result.xml).toContain('<QU>m3</QU>');
  });

  it('includes section labels as BoQCtgy with LblTx', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<BoQCtgy');
    expect(result.xml).toContain('<LblTx>Erdarbeiten</LblTx>');
    expect(result.xml).toContain('<LblTx>Betonarbeiten</LblTx>');
  });

  it('generates correct filename for X83', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X83' }));
    expect(result.filename).toMatch(/\.x83$/);
  });

  it('generates correct filename for X81', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X81' }));
    expect(result.filename).toMatch(/\.x81$/);
  });

  it('escapes XML special characters in descriptions', () => {
    const positionsWithSpecialChars: ExportPosition[] = [
      {
        id: 'pos-special',
        ordinal: '01.001',
        description: 'Wall > 2m & "thick" <special>',
        unit: 'm2',
        quantity: 10,
        unitRate: 100,
        total: 1000,
      },
    ];
    const result = generateGAEBXML(makeOptions({ positions: positionsWithSpecialChars }));
    expect(result.xml).toContain('&gt;');
    expect(result.xml).toContain('&amp;');
    expect(result.xml).toContain('&quot;');
    expect(result.xml).toContain('&lt;');
  });

  it('handles empty positions list', () => {
    const result = generateGAEBXML(makeOptions({ positions: [] }));
    expect(result.positionCount).toBe(0);
    expect(result.xml).toContain('<GAEB');
    expect(result.xml).toContain('</GAEB>');
  });

  it('includes AwardInfo with bidder details in X83', () => {
    const result = generateGAEBXML(
      makeOptions({
        format: 'X83',
        awardInfo: { bidderName: 'Baufirma GmbH', bidderCity: '10115 Berlin' },
      }),
    );
    expect(result.xml).toContain('<AwardInfo>');
    expect(result.xml).toContain('<Name1>Baufirma GmbH</Name1>');
    expect(result.xml).toContain('<PCode>10115 Berlin</PCode>');
  });

  it('includes ShortText (truncated to 70 chars)', () => {
    const longDesc = 'A'.repeat(100);
    const positions: ExportPosition[] = [
      { id: '1', ordinal: '01', description: longDesc, unit: 'm', quantity: 1, unitRate: 1, total: 1 },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    expect(result.xml).toContain('<ShortText>');
    // ShortText should be truncated
    const shortTextMatch = result.xml.match(/<ShortText>(.*?)<\/ShortText>/);
    expect(shortTextMatch).not.toBeNull();
    expect(shortTextMatch![1].length).toBeLessThanOrEqual(70);
  });

  it('includes BoQ name in BoQInfo', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<Name>Hauptangebot LV</Name>');
    expect(result.xml).toContain('<LblBoQ>Hauptangebot LV</LblBoQ>');
  });
});
