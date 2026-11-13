# Demo drawing set (DWG original)

`residential_block_set_v<N>.dwg` is the DWG original of the platform's demo drawing
set: a three-storey residential block with six apartments, eight A3 sheets side by
side in model space (units mm, layers named after the AIA convention). `<N>` is
`SET_VERSION` in `app/scripts/demo_drawing_set.py`.

- Authored by DataDrivenConstruction. The drawings are original works.
- Released under CC0-1.0 (public domain dedication), see `LICENSE`.
- Written as DWG R2000 from the generated DXF with LibreDWG 0.14 `dxf2dwg`
  (GNU LibreDWG, GPL-3.0). LibreDWG is used only offline, to produce these files;
  it is not part of the platform and is not needed to run it.

Rebuild (after changing the drawing, which also means bumping `SET_VERSION`):

    python scripts/build_demo_drawing_set.py --out set.dxf --dwg <path-to-dxf2dwg>

The demo seed keeps the DXF as the working file the DWG Takeoff viewer parses and
stores this DWG beside it as the original. Reading a DWG in the platform goes
through the DDC cad2data converter, never through LibreDWG.
