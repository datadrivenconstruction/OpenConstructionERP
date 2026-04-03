# User Journey — OpenEstimator.io

## Complete User Flow (every screen, every button)

### 1. FIRST VISIT → Registration
```
Landing: openestimator.io
  → "Get Started" → /register
  → Full name, email, password (with strength meter)
  → Auto-login → Dashboard
```

### 2. ONBOARDING → AI Setup
```
Dashboard (first time):
  → Banner: "Set up AI to get instant estimates"
  → Click → /settings → AI Configuration
  → Enter API key (Anthropic/OpenAI/Gemini)
  → Test Connection → "Connected ✅"
  → Back to Dashboard
```

### 3. QUICK ESTIMATE (AI-powered)
```
Sidebar: "AI Estimate" (with sparkle icon)
  → /ai-estimate
  → Textarea: "3-story residential building, 1200m², Berlin"
  → Select: Location, Currency, Standard
  → Click "Generate Estimate ✨"
  → Loading: animated dots, "AI is analyzing your project..."
  → Results: table with 20-30 positions
  → Click "Save as BOQ"
    → Select existing project OR create new
    → BOQ created with all positions
    → Navigate to BOQ editor
```

### 4. TRADITIONAL WORKFLOW
```
Projects → New Project
  → Name, description, region, currency, standard
  → Created → Project Dashboard

Project Dashboard:
  → Summary cards (budget, BOQs, positions, validation)
  → "New BOQ" → Create BOQ
  → BOQ Editor:
    → Add Section (e.g., "01. Erdarbeiten")
    → Add Position under section
    → Inline edit: description, unit, qty, rate
    → Auto-calc total
    → Add Markups (BGK, AGK, W&G)
    → Validate → see score
    → Export → PDF / Excel / CSV
```

### 5. IMPORT WORKFLOWS
```
a) Excel/CSV Import:
   Project → BOQ → Import button
   → Drag-and-drop .xlsx/.csv
   → Auto-detect columns (EN/DE)
   → Import summary → positions added

b) Photo Estimate:
   AI Estimate → "Upload Photo" tab
   → Drop building photo
   → AI analyzes: dimensions, materials, floors
   → Generated BOQ items
   → Save as BOQ

c) PDF Import:
   Project → BOQ → Import → PDF
   → Upload PDF with tables
   → Parse tables → extract positions
   → Import summary

d) Text Paste:
   BOQ Editor → "Paste from clipboard"
   → Paste tab-separated data
   → Auto-detect columns → create positions
```

### 6. COST DATABASE
```
Sidebar: "Cost Database"
  → Search: "beton" → results
  → Filter by unit, source
  → Click item → copy rate
  → Use in BOQ or Assembly
```

### 7. ASSEMBLIES (Calculations)
```
Sidebar: "Assemblies"
  → New Assembly: "RC Wall C30/37"
  → Add components from cost database
  → Set factors (0.25 m³/m², 25 kg/m²)
  → Auto-calc assembly rate
  → "Apply to BOQ" → select BOQ + quantity
```

### 8. VALIDATION
```
Sidebar: "Validation"
  → Select project → select BOQ
  → "Run Validation"
  → Traffic light: 99% score
  → List of warnings/errors
  → Click → go to position in BOQ
```

### 9. 4D SCHEDULE
```
Sidebar: "4D Schedule"
  → Select project → create schedule
  → Add activities (dates, WBS)
  → Gantt chart view
  → Link BOQ positions to activities
  → Track progress
```

### 10. 5D COST MODEL
```
Sidebar: "5D Cost Model"
  → Select project
  → "Generate Budget from BOQ"
  → KPI cards (budget, committed, actual, forecast)
  → S-curve chart
  → Budget by category table
  → Create monthly snapshots
```

### 11. SETTINGS
```
Sidebar: "Settings"
  → Profile (name, email, role)
  → AI Configuration (API keys)
  → Language (20 languages with flags)
  → Sign Out
```

### 12. KEYBOARD SHORTCUTS
```
Press ? → shortcuts dialog
g→d Dashboard, g→p Projects
n→p New Project
/ Search
```

## Every Button Must Work Checklist

### Login Page
- [x] Email input
- [x] Password input with show/hide
- [x] "Forgot password?" link
- [x] "Sign in" button → login + redirect
- [x] "Create account" link → /register

### Register Page
- [x] Full name, email, password, confirm
- [x] Password strength meter
- [x] "Create account" button → register + auto-login
- [x] "Sign in" link → /login

### Dashboard
- [x] "New Project" button → /projects/new
- [x] Project cards → click → /projects/:id
- [x] "Projects" link → /projects
- [x] System status live dot

### Projects List
- [x] "New Project" button
- [x] Project cards → click → detail

### Project Detail
- [x] Back to projects
- [x] "New BOQ" button → /projects/:id/boq/new
- [x] BOQ list items → click → /boq/:id
- [x] "Import" button per BOQ → import dialog
- [x] Import dialog: drop file, import, done

### BOQ Editor
- [x] Back to project
- [x] "Add Section" button
- [x] "Add Position" button
- [x] Inline edit (click cell → edit → blur/enter → save)
- [x] Delete button (hover → trash icon)
- [x] "Validate" button → /validation
- [x] "Export" dropdown → Excel / CSV / PDF
- [x] Section collapse/expand
- [x] Markups footer

### Cost Database
- [x] Search input → results
- [x] Unit filter
- [x] Source filter
- [x] Load more pagination

### Assemblies
- [x] "New Assembly" button
- [x] Assembly cards → click → editor
- [x] "Add Component" button
- [x] Inline edit components
- [x] "Apply to BOQ" button

### Validation
- [x] Project list → click → BOQ list
- [x] "Run Validation" button per BOQ
- [x] Traffic light results
- [x] Rule details expandable

### Schedule
- [x] Project list → click
- [x] "Create Schedule" button + modal
- [x] "Add Activity" button + modal
- [x] Gantt chart rendering
- [x] Progress slider

### 5D Cost Model
- [x] Project list → click
- [x] "Generate Budget" button
- [x] "Create Snapshot" button
- [x] "Generate Cash Flow" button
- [x] KPI cards display
- [x] S-curve chart
- [x] Budget table

### Settings
- [x] Profile card
- [x] AI Configuration (API keys) — NEW
- [x] Language grid → click to change
- [x] "Sign Out" button

### Header
- [x] Search button / "/"
- [x] Search input → Enter → search costs
- [x] Language dropdown
- [x] User menu → Profile, Settings, Sign Out
- [x] "?" keyboard shortcuts button

### AI Estimate — NEW
- [ ] Text description input
- [ ] Location/currency/standard selectors
- [ ] "Generate Estimate" button
- [ ] Results table
- [ ] "Save as BOQ" button
- [ ] "Export PDF" button
- [ ] Photo upload tab
