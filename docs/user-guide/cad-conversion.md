# CAD conversion queue and conversion errors

Upload a Revit, IFC or DWG file and see what the converter is doing, or why it cannot start.

Open **BIM** and upload the model.

1. Upload the file. One converter runs at a time, so a second upload shows **Waiting for the converter** until the first one finishes. The queue length is set with `OE_CONVERT_MAX_PARALLEL`.
2. When conversion ends, the model opens. A placeholder model with boxes carries a banner that says why: the converter on this machine produced no meshes, or no converter is installed.
3. If the status is **Needs Converter**, install the DDC converter named in the message and upload again. An IFC file is always read through the DDC converter; the platform does not fall back to a text parser for real IFC files.
4. A failed upload gives a plain message for network errors, files that are too large and too many requests, not a raw error text. Upload, re-process and delete are hidden from roles the server would refuse.

## What the validation rules warn about

- `bim.model.elements_have_category`: lists elements whose category is empty or unknown.
- `bim.model.zero_quantities`: lists elements with all-zero quantities, or warns when no element has a quantity at all.
