# Catatan: OpenConstructionERP

Ringkasan singkat hasil eksplorasi repo ini.

## Apa ini?

OpenConstructionERP adalah ERP open-source (AGPL-3.0) untuk industri konstruksi: BOQ (Bill of Quantities), takeoff dari PDF/CAD/BIM, dan pencocokan biaya berbasis AI. Mendukung 27+ bahasa dan 30+ standar regional (DIN 276, NRM, MasterFormat, GAEB, dll).

## Bagaimana data Revit (.rvt) diambil?

Tidak pakai Revit API maupun IFC + IfcOpenShell. Repo ini memakai komponen **DDC cad2data** — converter mandiri yang membaca file `.rvt`, `.ifc`, `.dwg`, `.dgn` langsung dan mengubahnya ke JSON terstruktur (elemen + quantity + properti), tanpa perlu Revit terinstall.

Alur singkatnya:

```
.rvt file → DDC cad2data (extract) → canonical JSON
   → match-elements (klasifikasi ke DIN/NRM/MasterFormat)
   → BOQ Editor (jadi baris estimasi dengan harga)
```

## VS Code vs Claude Code — kenapa tutorial biasanya pakai VS Code?

- **Pakai aplikasi saja** (`pip install openconstructionerp` lalu jalan di browser) — tidak perlu editor kode sama sekali.
- **Development / modifikasi source code** — di sinilah editor biasa dipakai. Tutorial umumnya condong ke VS Code karena ekosistem extension Python (Pylance) + TypeScript (frontend React) yang matang untuk proyek FastAPI + React seperti ini.
- **Claude Code bisa melakukan hal yang sama** — clone, install dependency, jalankan `make dev`, baca & perbaiki error — hanya lewat instruksi bahasa natural di terminal, bukan klik-klik UI editor. Repo ini tidak menyebutkan AI assistant tertentu karena ditulis generik untuk siapa pun.

## Stack teknis

| Layer | Teknologi |
|---|---|
| Backend | Python 3.12+ / FastAPI |
| Frontend | React 18 / TypeScript / Vite |
| Database | PostgreSQL 16 (embedded) / SQLite (dev) |
| CAD/BIM | DDC cad2data (RVT, IFC, DWG, DGN → JSON) |
| AI | Anthropic, OpenAI, Gemini, Mistral, Groq, DeepSeek |

## Sumber

- Repo asli: https://github.com/datadrivenconstruction/OpenConstructionERP
