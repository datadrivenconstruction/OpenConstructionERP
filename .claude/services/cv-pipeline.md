# CLAUDE.md — CV Pipeline Service

Parent: [../../CLAUDE.md](../../CLAUDE.md)

## Purpose

Computer vision pipeline for automated takeoff from PDF and photos.
Detects construction elements, extracts measurements, OCRs annotations.

## Pipeline

```
PDF/Photo input
    ↓
Page preprocessing (deskew, denoise, scale normalization)
    ↓
Zone detection (YOLOv11-OBB) → drawing area, legend, title block, tables
    ↓
Per-zone processing:
  - Drawing zone → symbol detection (custom YOLO), line extraction (OpenCV)
  - Table zone → PaddleOCR PP-StructureV3 → structured table data
  - Legend zone → OCR → symbol-to-description mapping
  - Title block → OCR → project metadata
    ↓
Assembly: combine zones into structured takeoff result
    ↓
Output: list of detected elements with quantities + confidence scores
```

## Stack

- PaddleOCR 3.0 (Apache 2.0) — OCR and table extraction
- YOLOv11 (AGPL) — object detection
- OpenCV — image preprocessing
- PyMuPDF — PDF to image conversion

## Output

Every AI result has a confidence score (0.0 - 1.0).
User MUST review before accepting. No auto-apply.
