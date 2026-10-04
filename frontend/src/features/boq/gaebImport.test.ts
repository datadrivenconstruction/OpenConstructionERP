// @ts-nocheck
/**
 * Unit tests for GAEB XML import parser.
 *
 * Tests cover:
 *  - X83 (Angebotsabgabe) with prices
 *  - X81 (Leistungsverzeichnis) without prices
 *  - Nested sections (BoQCtgy inside BoQCtgy)
 *  - Missing / malformed XML
 *  - Edge cases: missing Qty, missing UP, custom ordinals
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  parseGAEBXML,
  importGAEBToBOQ,
  decodeXmlBuffer,
  detectGAEBPhase,
  isGAEBSitePhase,
} from './gaebImport';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wrap content in a minimal valid GAEB X83 document. */
function x83Doc(boqBodyContent: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<GAEB>
  <GAEBInfo>
    <Date>2024-01-15</Date>
    <Conversion>3.3</Conversion>
  </GAEBInfo>
  <Award>
    <BoQ>
      <BoQBody>
        ${boqBodyContent}
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>`;
}

/** Wrap content in a minimal valid GAEB X81 document (no prices). */
function x81Doc(boqBodyContent: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<GAEB>
  <GAEBInfo>
    <Date>2024-01-15</Date>
    <Conversion>3.3</Conversion>
  </GAEBInfo>
  <Tender>
    <BoQ>
      <BoQBody>
        ${boqBodyContent}
      </BoQBody>
    </BoQ>
  </Tender>
</GAEB>`;
}

/** Build a single Item XML fragment. */
function itemXML(opts: {
  rno: string;
  qty?: string;
  qu?: string;
  text?: string;
  up?: string;
}): string {
  const { rno, qty = '10', qu = 'm2', text = 'Test position', up } = opts;
  return `
    <Item RNoPart="${rno}">
      <Qty>${qty}</Qty>
      <QU>${qu}</QU>
      <Description>
        <CompleteText>
          <DetailTxt>
            <Text>${text}</Text>
          </DetailTxt>
        </CompleteText>
      </Description>
      ${up !== undefined ? `<UP>${up}</UP>` : ''}
    </Item>`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('parseGAEBXML', () => {
  // ── Test 1: Simple X83 with two positions ────────────────────────────────
  it('parses a simple X83 with two positions', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '20', qu: 'm2', text: 'Concrete slab C30/37', up: '85.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Reinforcement B500B', up: '1200.50' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);

    expect(result[0].ordinal).toBe('001');
    expect(result[0].description).toBe('Concrete slab C30/37');
    expect(result[0].unit).toBe('m2');
    expect(result[0].quantity).toBe(20);
    expect(result[0].unitRate).toBe(85.0);

    expect(result[1].ordinal).toBe('002');
    expect(result[1].description).toBe('Reinforcement B500B');
    expect(result[1].unit).toBe('m3');
    expect(result[1].quantity).toBe(5);
    expect(result[1].unitRate).toBe(1200.5);
  });

  // ── Test 2: Nested sections (BoQCtgy inside BoQCtgy) ────────────────────
  it('parses nested BoQCtgy sections and builds compound ordinals', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="01">
        <LblTx>Earthworks</LblTx>
        <BoQBody>
          <BoQCtgy RNoPart="01">
            <LblTx>Excavation</LblTx>
            <BoQBody>
              <Itemlist>
                ${itemXML({ rno: '001', qty: '150', qu: 'm3', text: 'Bulk excavation', up: '12.00' })}
              </Itemlist>
            </BoQBody>
          </BoQCtgy>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].ordinal).toBe('01.01.001');
    expect(result[0].description).toBe('Bulk excavation');
    expect(result[0].quantity).toBe(150);
    expect(result[0].unit).toBe('m3');
    expect(result[0].unitRate).toBe(12.0);
  });

  // ── Test 3: Missing Qty defaults to 0 ────────────────────────────────────
  it('defaults quantity to 0 when Qty element is missing', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <QU>Stk</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Door frame</Text></DetailTxt></CompleteText>
          </Description>
          <UP>350.00</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].quantity).toBe(0);
    expect(result[0].unit).toBe('Stk');
    expect(result[0].unitRate).toBe(350.0);
  });

  // ── Test 4: Missing UP defaults to 0 ─────────────────────────────────────
  it('defaults unitRate to 0 when UP element is missing', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm', text: 'Perimeter fence' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].unitRate).toBe(0);
    expect(result[0].quantity).toBe(10);
  });

  // ── Test 5: Extract unit from QU tag ─────────────────────────────────────
  it('extracts unit of measure from QU element', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qu: 'lfd.m', text: 'Steel beam', up: '75.00' })}
        ${itemXML({ rno: '002', qu: 'Stk', text: 'Anchor bolt', up: '2.50' })}
        ${itemXML({ rno: '003', qu: 'Psch', text: 'Lump sum cleaning', up: '500.00' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result[0].unit).toBe('lfd.m');
    expect(result[1].unit).toBe('Stk');
    expect(result[2].unit).toBe('Psch');
  });

  // ── Test 6: Build ordinal from OrdinalNo / RNoPart ───────────────────────
  it('builds hierarchical ordinal from category and item RNoPart attributes', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="02">
        <LblTx>Concrete Works</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '010', qty: '45', qu: 'm3', text: 'In-situ concrete', up: '220.00' })}
            ${itemXML({ rno: '011', qty: '120', qu: 'm2', text: 'Formwork', up: '35.00' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);
    expect(result[0].ordinal).toBe('02.010');
    expect(result[1].ordinal).toBe('02.011');
  });

  // ── Test 7: Handle empty XML string ──────────────────────────────────────
  it('returns empty array for empty XML string', () => {
    expect(parseGAEBXML('')).toEqual([]);
    expect(parseGAEBXML('   ')).toEqual([]);
  });

  // ── Test 8: Handle malformed XML ─────────────────────────────────────────
  it('returns empty array for malformed XML', () => {
    const malformed = '<GAEB><Award><BoQ><BoQBody><Itemlist><Item>UNCLOSED';
    const result = parseGAEBXML(malformed);
    // DOMParser is lenient — it will try to recover. What matters is no crash,
    // and if it does produce a parsererror document we return [].
    expect(Array.isArray(result)).toBe(true);
  });

  // ── Test 9: X81 format — no prices ───────────────────────────────────────
  it('parses X81 Leistungsverzeichnis with no unit prices', () => {
    const xml = x81Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>250</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText>
              <DetailTxt><Text>Tiling 30x30cm</Text></DetailTxt>
            </CompleteText>
          </Description>
        </Item>
        <Item RNoPart="002">
          <Qty>80</Qty>
          <QU>m</QU>
          <Description>
            <CompleteText>
              <DetailTxt><Text>Skirting board</Text></DetailTxt>
            </CompleteText>
          </Description>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);
    expect(result[0].unitRate).toBe(0);
    expect(result[1].unitRate).toBe(0);
    expect(result[0].description).toBe('Tiling 30x30cm');
    expect(result[1].description).toBe('Skirting board');
  });

  // ── Test 10: Extract section headers from LblTx ──────────────────────────
  it('attaches section label from ancestor BoQCtgy LblTx to positions', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="03">
        <LblTx>Masonry Works</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '001', qty: '200', qu: 'm2', text: 'Brick wall 24cm', up: '65.00' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].section).toBe('Masonry Works');
    expect(result[0].ordinal).toBe('03.001');
  });

  // ── Test 11: Comma decimal separator (German locale) ─────────────────────
  it('handles comma as decimal separator in Qty and UP values', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>12,5</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Floor screed</Text></DetailTxt></CompleteText>
          </Description>
          <UP>48,75</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].quantity).toBe(12.5);
    expect(result[0].unitRate).toBe(48.75);
  });

  // ── Test 11b: German thousands + decimal separators (1.234,56) ──────────
  it('parses German-formatted numbers with dot thousands + comma decimal', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>1.250,5</Qty>
          <QU>m3</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Bulk concrete</Text></DetailTxt></CompleteText>
          </Description>
          <UP>1.234,56</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    // Previously "1.234,56" was truncated to 1.234 by a naive replace(',', '.').
    expect(result[0].quantity).toBe(1250.5);
    expect(result[0].unitRate).toBe(1234.56);
  });

  // ── Test 11c: US thousands + dot decimal (1,234.56) ─────────────────────
  it('parses US-formatted numbers with comma thousands + dot decimal', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>10</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Slab area</Text></DetailTxt></CompleteText>
          </Description>
          <UP>1,234.56</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    // Both separators present, dot last -> comma is the thousands group.
    expect(result[0].quantity).toBe(10);
    expect(result[0].unitRate).toBe(1234.56);
  });

  // ── Test 12: Qty as attribute on BoQCtgy (GAEB variant) ──────────────────
  it('reads Qty from Item child element when attribute is absent', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="005">
          <Qty>33</Qty>
          <QU>m3</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Sand fill</Text></DetailTxt></CompleteText>
          </Description>
          <UP>18.00</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result[0].quantity).toBe(33);
    expect(result[0].unitRate).toBe(18);
  });

  // ── Test 13: Multi-paragraph descriptions preserve line breaks ──────────
  it('preserves paragraph breaks when DetailTxt has multiple Text children', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>10</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText>
              <DetailTxt>
                <Text>First paragraph: technical description.</Text>
                <Text>Second paragraph: installation notes.</Text>
                <Text>Third paragraph: acceptance criteria.</Text>
              </DetailTxt>
            </CompleteText>
          </Description>
          <UP>50.00</UP>
        </Item>
      </Itemlist>
    `);
    const result = parseGAEBXML(xml);
    expect(result).toHaveLength(1);
    // All three paragraphs joined by newline
    expect(result[0].description).toContain('First paragraph');
    expect(result[0].description).toContain('Second paragraph');
    expect(result[0].description).toContain('Third paragraph');
    expect(result[0].description.split('\n')).toHaveLength(3);
  });

  // ── Test 14: Single-paragraph description still works after fix ─────────
  it('handles single-paragraph descriptions identically to multi-paragraph', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>5</Qty>
          <QU>m</QU>
          <Description>
            <CompleteText>
              <DetailTxt>
                <Text>Steel beam HEB 200,   length 5m,    inkl. Korrosionsschutz</Text>
              </DetailTxt>
            </CompleteText>
          </Description>
          <UP>120.00</UP>
        </Item>
      </Itemlist>
    `);
    const result = parseGAEBXML(xml);
    expect(result).toHaveLength(1);
    // Internal multiple-spaces should still be collapsed to one
    expect(result[0].description).toBe('Steel beam HEB 200, length 5m, inkl. Korrosionsschutz');
  });
});

// ---------------------------------------------------------------------------
// Real-world fixture: the namespaced Frankfurt Rohbau X83 (camera repro)
// ---------------------------------------------------------------------------

describe('parseGAEBXML on the Frankfurt Rohbau X83 fixture', () => {
  // The exact file the German pilot imports on camera. Unlike the synthetic
  // documents above it carries the real GAEB default namespace, LblTx as
  // <p><span> and the 2+2+4 OZ mask - so this pins the CLIENT pipeline
  // against the same oracle the backend importer tests use.
  const readFixture = async (): Promise<string> => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    // Vitest runs with cwd = frontend/, the fixture lives in the sibling
    // backend test tree (single repo, both pipelines share the oracle file).
    return readFileSync(
      resolve(process.cwd(), '..', 'backend', 'tests', 'fixtures', 'gaeb', 'frankfurt_rohbau_x83.x83'),
      'utf-8',
    );
  };

  it('parses all 21 positions with their full section hierarchy', async () => {
    const result = parseGAEBXML(await readFixture());

    expect(result).toHaveLength(21);

    // Every position sits inside the Rohbau Gewerk and one of its five
    // sub-sections; the innermost path entry matches the item's own OZ.
    const subSections = new Set<string>();
    for (const pos of result) {
      expect(pos.sectionPath?.[0]).toEqual({ ordinal: '01', label: 'Rohbau' });
      expect(pos.sectionPath).toHaveLength(2);
      const inner = pos.sectionPath![1];
      expect(pos.ordinal.startsWith(`${inner.ordinal}.`)).toBe(true);
      subSections.add(`${inner.ordinal} ${inner.label}`);
    }
    expect(subSections).toEqual(
      new Set([
        '01.01 Baustelleneinrichtung',
        '01.02 Erdarbeiten',
        '01.03 Beton- und Stahlbetonarbeiten',
        '01.04 Mauerwerksarbeiten',
        '01.05 Abdichtungsarbeiten',
      ]),
    );

    // Umlauts and non-round quantities survive (the camera checks).
    const blob = result.map((p) => p.description).join('\n');
    expect(blob).toContain('Bewehrung');
    expect(result.some((p) => p.quantity === 386.5)).toBe(true);

    // An Angebotsaufforderung carries no prices - nothing to lose on import.
    expect(result.every((p) => p.unitRate === 0)).toBe(true);
  });

  it('detects the fixture as X83 by phase, not by price presence', async () => {
    expect(detectGAEBPhase(await readFixture())).toBe('X83');
  });
});

// ---------------------------------------------------------------------------
// detectGAEBPhase — the badge must state the file's phase, not guess from prices
// ---------------------------------------------------------------------------

describe('detectGAEBPhase', () => {
  it('reads the phase from Award/DP - an unpriced X83 is NOT an X81', () => {
    // Frankfurt-fixture shape: DP 83, namespaced root, zero prices. The old
    // price heuristic labelled exactly this file "X81" on camera.
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
  <Award>
    <DP>83</DP>
    <BoQ><BoQBody><Itemlist>
      <Item RNoPart="0010"><Qty>1</Qty><QU>psch</QU></Item>
    </Itemlist></BoQBody></BoQ>
  </Award>
</GAEB>`;
    expect(detectGAEBPhase(xml)).toBe('X83');
  });

  it('detects a priced bid submission as X84, not X83', () => {
    const xml = `<?xml version="1.0"?><GAEB><Award><DP>84</DP></Award></GAEB>`;
    expect(detectGAEBPhase(xml)).toBe('X84');
  });

  it('falls back to the DAnn token in the root namespace when DP is absent', () => {
    const xml = `<?xml version="1.0"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA81/3.3"><Tender><BoQ/></Tender></GAEB>`;
    expect(detectGAEBPhase(xml)).toBe('X81');
  });

  it('returns an empty string when the phase cannot be determined', () => {
    expect(detectGAEBPhase('<GAEB><Award><BoQ/></Award></GAEB>')).toBe('');
    expect(detectGAEBPhase('')).toBe('');
    expect(detectGAEBPhase('garbage <')).toBe('');
  });

  it('names a measurement and an invoice, which are not bills', () => {
    const x31 = `<?xml version="1.0"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3"><QtyDeterm><DP>31</DP><BoQ/></QtyDeterm></GAEB>`;
    const x89 = `<?xml version="1.0"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA89/3.3"><Invoice><DP>89</DP></Invoice></GAEB>`;
    expect(detectGAEBPhase(x31)).toBe('X31');
    expect(detectGAEBPhase(x89)).toBe('X89');
    expect(isGAEBSitePhase('X31')).toBe(true);
    expect(isGAEBSitePhase('X89')).toBe(true);
    expect(isGAEBSitePhase('X83')).toBe(false);
    expect(isGAEBSitePhase('')).toBe(false);
  });
});

describe('importGAEBToBOQ refuses the site phases', () => {
  it('posts nothing for an X89 invoice', async () => {
    const { boqApi } = await import('./api');
    const addPosition = vi.spyOn(boqApi, 'addPosition');
    const addSection = vi.spyOn(boqApi, 'addSection');
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA89/3.3"><Invoice><DP>89</DP><BoQ><BoQBody><Itemlist>
<Item RNoPart="0010"><BillQty>1</BillQty><QU>m3</QU><UP>10</UP><IT>10</IT></Item>
</Itemlist></BoQBody></BoQ></Invoice></GAEB>`;
    const file = new File([xml], 'rechnung.xml', { type: 'application/xml' });
    await expect(importGAEBToBOQ(file, 'boq-1')).rejects.toThrow('X89');
    expect(addPosition).not.toHaveBeenCalled();
    expect(addSection).not.toHaveBeenCalled();
    addPosition.mockRestore();
    addSection.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// decodeXmlBuffer — encoding sniffing tests
// ---------------------------------------------------------------------------

describe('decodeXmlBuffer', () => {
  it('decodes a UTF-8 prolog as UTF-8', () => {
    const xml = '<?xml version="1.0" encoding="UTF-8"?><GAEB><x>äöü</x></GAEB>';
    const bytes = new TextEncoder().encode(xml);
    const decoded = decodeXmlBuffer(bytes.buffer);
    expect(decoded).toContain('äöü');
  });

  it('decodes an ISO-8859-1 prolog as Latin-1 (preserves umlauts)', () => {
    // Build a Latin-1 byte sequence manually: ä=0xE4, ö=0xF6, ü=0xFC, ß=0xDF
    const prolog = '<?xml version="1.0" encoding="ISO-8859-1"?><GAEB><x>';
    const suffix = '</x></GAEB>';
    const prologBytes = Array.from(prolog).map((c) => c.charCodeAt(0));
    const umlautBytes = [0xe4, 0xf6, 0xfc, 0xdf]; // ä ö ü ß in Latin-1
    const suffixBytes = Array.from(suffix).map((c) => c.charCodeAt(0));
    const buffer = new Uint8Array([...prologBytes, ...umlautBytes, ...suffixBytes]).buffer;

    const decoded = decodeXmlBuffer(buffer);
    expect(decoded).toContain('äöüß');
    // Critically: U+FFFD (replacement char) should NOT appear — that's what
    // the broken UTF-8-only path would have produced.
    expect(decoded).not.toContain('\ufffd');
  });

  it('decodes a Windows-1252 prolog correctly', () => {
    const prolog = '<?xml version="1.0" encoding="Windows-1252"?><GAEB><x>';
    const suffix = '</x></GAEB>';
    const prologBytes = Array.from(prolog).map((c) => c.charCodeAt(0));
    // Windows-1252: same as Latin-1 for these chars
    const umlautBytes = [0xe4, 0xf6, 0xfc, 0xdf];
    const suffixBytes = Array.from(suffix).map((c) => c.charCodeAt(0));
    const buffer = new Uint8Array([...prologBytes, ...umlautBytes, ...suffixBytes]).buffer;

    const decoded = decodeXmlBuffer(buffer);
    expect(decoded).toContain('äöüß');
  });

  it('falls back to UTF-8 when no encoding is declared', () => {
    const xml = '<?xml version="1.0"?><GAEB><x>äöü</x></GAEB>';
    const bytes = new TextEncoder().encode(xml);
    const decoded = decodeXmlBuffer(bytes.buffer);
    expect(decoded).toContain('äöü');
  });
});

// ---------------------------------------------------------------------------
// Section hierarchy parsing (K-3: sections were lost on import)
// ---------------------------------------------------------------------------

describe('parseGAEBXML section hierarchy', () => {
  // The German pilot QA (K-3) caught the import preview showing a filled
  // "Abschnitt" column while the imported BOQ ended up with "0 Abschnitte":
  // the parser only carried the nearest label, and the importer dropped it.
  // Positions must now carry the FULL BoQCtgy chain so the importer can
  // recreate the section rows.
  it('emits the full BoQCtgy path (ordinal + label) on every position', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="01">
        <LblTx>Rohbau</LblTx>
        <BoQBody>
          <BoQCtgy RNoPart="01">
            <LblTx>Baustelleneinrichtung</LblTx>
            <BoQBody>
              <Itemlist>
                ${itemXML({ rno: '0010', qty: '1', qu: 'psch', text: 'Baustelle einrichten' })}
              </Itemlist>
            </BoQBody>
          </BoQCtgy>
          <BoQCtgy RNoPart="02">
            <LblTx>Erdarbeiten</LblTx>
            <BoQBody>
              <Itemlist>
                ${itemXML({ rno: '0010', qty: '1485.5', qu: 'm2', text: 'Oberboden abtragen' })}
              </Itemlist>
            </BoQBody>
          </BoQCtgy>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);
    expect(result[0].sectionPath).toEqual([
      { ordinal: '01', label: 'Rohbau' },
      { ordinal: '01.01', label: 'Baustelleneinrichtung' },
    ]);
    expect(result[1].sectionPath).toEqual([
      { ordinal: '01', label: 'Rohbau' },
      { ordinal: '01.02', label: 'Erdarbeiten' },
    ]);
    // The preview's nearest-label field keeps working unchanged.
    expect(result[0].section).toBe('Baustelleneinrichtung');
    expect(result[1].section).toBe('Erdarbeiten');
  });

  it('leaves sectionPath empty for items outside any BoQCtgy', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Ungrouped item', up: '5.00' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].sectionPath ?? []).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// importGAEBToBOQ tests
// ---------------------------------------------------------------------------

/** Full Position-shaped API response for mocks. */
function makePositionResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: 'pos-new',
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '001',
    description: 'Test',
    unit: 'm2',
    quantity: 10,
    unit_rate: 50,
    total: 500,
    classification: {},
    source: 'gaeb_import',
    confidence: null,
    validation_status: 'pending',
    sort_order: 0,
    metadata: {},
    ...overrides,
  };
}

/** Nested two-sub-section GAEB body mirroring the Frankfurt fixture shape. */
const NESTED_SECTIONS_BODY = `
  <BoQCtgy RNoPart="01">
    <LblTx>Rohbau</LblTx>
    <BoQBody>
      <BoQCtgy RNoPart="01">
        <LblTx>Baustelleneinrichtung</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '0010', qty: '1', qu: 'psch', text: 'Baustelle einrichten' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
      <BoQCtgy RNoPart="02">
        <LblTx>Erdarbeiten</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '0010', qty: '1485.5', qu: 'm2', text: 'Oberboden abtragen' })}
            ${itemXML({ rno: '0020', qty: '3862.25', qu: 'm3', text: 'Boden loesen' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
    </BoQBody>
  </BoQCtgy>
`;

describe('importGAEBToBOQ section preservation (K-3)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('creates one section row per BoQCtgy and parents positions under the innermost one', async () => {
    const { boqApi } = await import('./api');

    const sectionCalls = [];
    let sectionSeq = 0;
    vi.spyOn(boqApi, 'addSection').mockImplementation(async (boqId, data) => {
      sectionSeq += 1;
      const id = `sec-${sectionSeq}`;
      sectionCalls.push({ id, boqId, ...data });
      return makePositionResponse({
        id,
        ordinal: data.ordinal,
        description: data.description,
        unit: 'section',
        quantity: 0,
        unit_rate: 0,
        total: 0,
        parent_id: data.parent_id ?? null,
      });
    });

    const positionCalls = [];
    vi.spyOn(boqApi, 'addPosition').mockImplementation(async (data) => {
      positionCalls.push(data);
      return makePositionResponse({ id: `pos-${positionCalls.length}` });
    });

    const file = new File([x83Doc(NESTED_SECTIONS_BODY)], 'frankfurt.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    // Sections created in document order, once each, with the LV hierarchy.
    expect(sectionCalls.map((c) => c.ordinal)).toEqual(['01', '01.01', '01.02']);
    expect(sectionCalls.map((c) => c.description)).toEqual([
      'Rohbau',
      'Baustelleneinrichtung',
      'Erdarbeiten',
    ]);
    expect(sectionCalls[0].parent_id ?? null).toBeNull();
    expect(sectionCalls[1].parent_id).toBe('sec-1');
    expect(sectionCalls[2].parent_id).toBe('sec-1');

    // Every position lands under its innermost section.
    expect(positionCalls).toHaveLength(3);
    expect(positionCalls[0].parent_id).toBe('sec-2');
    expect(positionCalls[1].parent_id).toBe('sec-3');
    expect(positionCalls[2].parent_id).toBe('sec-3');

    expect(result.imported).toBe(3);
    expect(result.sectionsCreated).toBe(3);
    expect(result.errors).toHaveLength(0);
  });

  it('falls back to the nearest created ancestor when a section create fails', async () => {
    const { boqApi } = await import('./api');

    let sectionSeq = 0;
    vi.spyOn(boqApi, 'addSection').mockImplementation(async (_boqId, data) => {
      if (data.ordinal === '01.01') {
        throw new Error('Section rejected');
      }
      sectionSeq += 1;
      return makePositionResponse({
        id: `sec-${sectionSeq}`,
        ordinal: data.ordinal,
        unit: 'section',
      });
    });

    const positionCalls = [];
    vi.spyOn(boqApi, 'addPosition').mockImplementation(async (data) => {
      positionCalls.push(data);
      return makePositionResponse({ id: `pos-${positionCalls.length}` });
    });

    const file = new File([x83Doc(NESTED_SECTIONS_BODY)], 'frankfurt.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    // The failed sub-section is reported once, not once per child row.
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain('01.01');

    // Its child attaches to the nearest created ancestor (Rohbau) instead
    // of silently losing the hierarchy entirely.
    expect(positionCalls[0].parent_id).toBe('sec-1');
    // The sibling section is unaffected.
    expect(positionCalls[1].parent_id).toBe('sec-2');
    expect(positionCalls[2].parent_id).toBe('sec-2');

    expect(result.imported).toBe(3);
    expect(result.sectionsCreated).toBe(2);
  });

  it('creates no sections for a flat document without BoQCtgy', async () => {
    const { boqApi } = await import('./api');

    const addSection = vi.spyOn(boqApi, 'addSection').mockResolvedValue(makePositionResponse());
    vi.spyOn(boqApi, 'addPosition').mockResolvedValue(makePositionResponse());

    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Flat item', up: '50.00' })}
      </Itemlist>
    `);
    const file = new File([xml], 'flat.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    expect(addSection).not.toHaveBeenCalled();
    expect(result.imported).toBe(1);
    expect(result.sectionsCreated).toBe(0);
  });
});

describe('importGAEBToBOQ', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('calls boqApi.addPosition for each parsed position and returns imported count', async () => {
    // Mock the boqApi module
    const { boqApi } = await import('./api');
    vi.spyOn(boqApi, 'addPosition').mockResolvedValue({
      id: 'pos-new',
      boq_id: 'boq-1',
      parent_id: null,
      ordinal: '001',
      description: 'Test',
      unit: 'm2',
      quantity: 10,
      unit_rate: 50,
      total: 500,
      classification: {},
      source: 'gaeb_import',
      confidence: null,
      validation_status: 'pending',
      sort_order: 0,
      metadata: {},
    });

    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Wall tiles', up: '50.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Foundation concrete', up: '220.00' })}
      </Itemlist>
    `);

    const file = new File([xml], 'test.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    expect(result.imported).toBe(2);
    expect(result.errors).toHaveLength(0);
    expect(boqApi.addPosition).toHaveBeenCalledTimes(2);
  });

  it('collects errors for positions that fail to POST and continues importing', async () => {
    const { boqApi } = await import('./api');
    let callCount = 0;
    vi.spyOn(boqApi, 'addPosition').mockImplementation(async () => {
      callCount++;
      if (callCount === 2) {
        throw new Error('Network error');
      }
      return {
        id: 'pos-new',
        boq_id: 'boq-1',
        parent_id: null,
        ordinal: '001',
        description: 'Test',
        unit: 'm2',
        quantity: 10,
        unit_rate: 50,
        total: 500,
        classification: {},
        source: 'gaeb_import',
        confidence: null,
        validation_status: 'pending',
        sort_order: 0,
        metadata: {},
      };
    });

    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Item A', up: '50.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Item B', up: '220.00' })}
        ${itemXML({ rno: '003', qty: '2', qu: 'Stk', text: 'Item C', up: '75.00' })}
      </Itemlist>
    `);

    const file = new File([xml], 'test.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    expect(result.imported).toBe(2);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain('Item B');
    expect(result.errors[0]).toContain('Network error');
  });
});
