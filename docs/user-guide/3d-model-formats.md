# Importing 3D models and mesh formats

This page answers one question: I have a 3D file that is not an IFC or a Revit model, can I get it into the platform and measure it. The short answer is yes, through a different door than raw CAD, and this page explains which door and what you get once you are through it.

## Two kinds of 3D file

The platform treats 3D files as two separate families, because they carry genuinely different things.

**Authored BIM and CAD files** carry semantics. An element in an IFC or a Revit model knows that it is a wall, which storey it sits on, what it is made of, which classification code applies to it. These go to the server, where the conversion pipeline turns them into the canonical format that the rest of the platform reads. The formats here are RVT, IFC, DWG and DGN.

**Mesh files** carry surfaces and nothing else. A triangle in an OBJ or a 3DS file does not know it belongs to a wall. There is no property set, no material in the construction sense, no classification. There is therefore nothing for a server-side converter to extract, and no converter is involved: these are read directly in your browser.

This distinction is not a limitation we chose, it is what the file formats actually contain. Knowing which family your file is in tells you what to expect from it.

## Mesh formats you can import

Drop any of these into the 3D uploader in the BIM Hub and they are read in the browser:

OBJ, STL, PLY, DAE (COLLADA), glTF, GLB, FBX, LWO and 3DS.

USD and USDZ are also accepted, but parsing them is best effort. The import dialog labels them experimental and asks you to check the extracted quantities before you commit, because a complex USD file can parse incompletely without failing outright.

Nothing is uploaded to the server until you confirm the import, so a file that will not parse costs you nothing but the time to pick it.

One practical point: give it a single self-contained file. Several of these formats can also be exported as a set of files, a `.gltf` with a separate `.bin` beside it, or an `.obj` with its `.mtl`. The importer reads only the file you hand it and cannot go looking for siblings.

For glTF that means the distinction is where the buffers live, not the extension. A `.gltf` that carries its buffers inside the file imports normally. A `.gltf` that points at an external `.bin` does not, and the simplest fix is to export `.glb`, which packs everything into one file. An `.obj` without its `.mtl` parses normally and simply arrives untextured, which changes no measurement.

## What the import gives you

The importer walks the parsed scene and measures every object it finds. For each one you get surface area, volume, longest extent and a bounding box, plus the triangle count. Totals are shown for the whole model.

Volume needs a caveat, and the dialog shows it rather than hiding it. A volume is only meaningful when a mesh is closed, and plenty of exported meshes are not. Objects that are watertight get an exact volume. Objects that are open contribute their surface area but their volume is reported as approximate and recorded in a separate column, so an approximate figure is never presented to you or to a client as an exact one.

Once you confirm, the import writes a normalized model file and an element table and hands both to the same upload the server-side converters feed. It is the same entry point, carrying the same two artefacts, so from there the model is an ordinary model: it opens in the same viewer, its objects appear in the element list, and they can be linked to BOQ positions, carried into takeoff, and exported. Nothing downstream needs to know the model started life as a mesh.

## Confirming scale and orientation

Two things a mesh file cannot reliably tell you are the unit its numbers are in and which axis points up. Different tools export different conventions and many formats do not record the answer at all.

So the import dialog asks you, and it shows you the model while you answer. The viewport renders it under exactly the transform the import will apply, against a ground grid labelled in metres. Change the unit or the axis and the model rebuilds immediately, which makes a wrong up-axis obvious straight away: the model is lying on its side.

Scale is checked differently, because a picture cannot show it. A model in millimetres and the same model in metres look exactly alike on screen, and the grid rescales with them, so nothing about the image tells you which one you have. Only the numbers do. So the dialog reads the numbers for you: it takes the largest dimension of the whole model, converts it to metres under the unit you picked, and if the answer falls outside the range a building plausibly occupies it says so and names the unit that would bring it back into range. Applying that unit is one click. The model's size in metres is also shown next to the quantities, so you can always check it yourself.

The warning never blocks an import. A handrail bracket measured on its own really is a few centimetres across, and you know your file better than a range check does. It is there to catch the mistake that costs the most, which is a factor-of-a-thousand unit error nobody noticed until it had been priced.

Get this right at import and everything downstream is right. Get it wrong and every area and volume is off by that same factor, which is why the step exists and why it is not skippable.

## What mesh import does not do

It does not invent BIM data. There are no properties to extract, no classification codes, no storey assignment, no material takeoff by specification. If you need those, you need a model that carries them, which means IFC or RVT.

A mesh import is the right tool when you have geometry and need quantities from it. It is the wrong tool when you were hoping to recover information the file never contained.

## If you upload a mesh to the wrong place

The raw CAD upload endpoint accepts RVT, IFC and DWG. If you send it a mesh file it will not silently store something that can never render. It refuses with a message naming your file and pointing you at the 3D uploader, and it explains that the format carries geometry only. The file manager does the same: mesh files are stored as ordinary documents and you are pointed at the importer that can actually read them.

## Where this lives

The classification and the guard messages are in the `bim_hub` backend module. The parsing, measurement, preview and export all run in the browser, in the `meshImport` part of the BIM feature. There is no separate module to install and no extra dependency to add.

## Related

- [BIM to cost and carbon (5D and 6D)](./bim-to-cost-and-carbon.md) for what happens after a model is in.
- [Quantity takeoff from drawings and models](./quantity-takeoff.md) for measuring from drawings rather than models.
