// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A file picked from the bill toolbar reaches the route that can read it.
//
// An XPWE export saved as ``computo.xml`` went to the smart route, which
// refuses ``.xml`` by extension ("Unsupported file type: .xml"), while the
// import dialog read it: the dialog lets the server tell formats apart by
// content. A plain ``.xml`` now goes to that same content-detecting route; a
// GAEB bill named as one still goes to the GAEB parser.

import { describe, expect, it } from 'vitest';
import { toolbarImportRoute } from './importRoute';

describe('toolbarImportRoute', () => {
  it.each([
    ['computo.xml', 'auto'],
    ['COMPUTO.XML', 'auto'],
    ['lv.xml', 'auto'],
    ['computo.xpwe', 'auto'],
    ['bill.bc3', 'auto'],
    ['progetto.dcf', 'auto'],
    ['progetto.pwe', 'auto'],
  ])('sends %s to the content-detecting route', (name, route) => {
    expect(toolbarImportRoute(name)).toBe(route);
  });

  it.each([
    ['lv.x83', 'gaeb'],
    ['lv.X84', 'gaeb'],
    ['angebot.x84.xml', 'gaeb'],
    ['lv.gaeb.xml', 'gaeb'],
  ])('keeps the GAEB bill %s on the GAEB parser', (name, route) => {
    expect(toolbarImportRoute(name)).toBe(route);
  });

  it.each([
    ['aufmass.x31', 'site'],
    ['rechnung.X89', 'site'],
    ['bill.xlsx', 'smart'],
    ['scan.pdf', 'smart'],
    ['noext', 'smart'],
  ])('routes %s as before', (name, route) => {
    expect(toolbarImportRoute(name)).toBe(route);
  });
});
