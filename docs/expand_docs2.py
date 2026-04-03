"""Expand docs.html with step-by-step tutorials for each module."""

html = open('docs/docs.html', encoding='utf-8').read()

# === 1. EXPAND Projects section (add after Overview, before Install) ===
# Add a "Getting Started" tutorial right after Overview

overview_end = '</section>\n\n<section id="install">'
projects_section = '''</section>

<section id="first-steps">
<h2>First Steps After Installation</h2>
<p>After installing OpenConstructionERP, follow these steps to set up your first project and create your first cost estimate. The entire process takes about 10 minutes.</p>

<h3 id="fs-login">Step 1: Log In</h3>
<p>Open your browser and navigate to <code>http://localhost:5173</code> (local development) or <code>http://localhost:8080</code> (Docker). You will see the login page with a "Demo Access" panel. Click on <strong>Admin</strong> to log in instantly with the demo account, or enter your own credentials if you registered a new account.</p>

<h3 id="fs-onboarding">Step 2: Complete Onboarding</h3>
<p>On first login, the onboarding wizard guides you through initial setup:</p>
<ol>
<li><strong>Choose your language</strong> &mdash; Select from 21 available languages. The entire UI switches immediately.</li>
<li><strong>Select your region</strong> &mdash; This determines which cost database and classification standard are used by default (e.g., DIN 276 for Germany, NRM for UK, MasterFormat for US).</li>
<li><strong>Configure AI (optional)</strong> &mdash; If you want AI estimation features, enter an API key from any supported provider (Anthropic, OpenAI, Gemini, etc.). You can skip this and add it later in Settings.</li>
<li><strong>Load cost database</strong> &mdash; The system offers to download and import the CWICR cost database for your selected region (55,719 items). This takes about 30 seconds.</li>
</ol>

<h3 id="fs-project">Step 3: Create Your First Project</h3>
<p>Click <strong>New Project</strong> on the Dashboard or navigate to Projects. Fill in:</p>
<ul>
<li><strong>Project name</strong> &mdash; e.g., "Residential Building Berlin-Mitte"</li>
<li><strong>Description</strong> &mdash; Brief scope description</li>
<li><strong>Region</strong> &mdash; Determines currency and default classification standard</li>
<li><strong>Classification standard</strong> &mdash; DIN 276, NRM 1/2, MasterFormat, or custom</li>
</ul>
<p>After creating the project, you are redirected to the project detail page where you can start adding BOQs.</p>

<h3 id="fs-boq">Step 4: Create Your First BOQ</h3>
<p>From the project page, click <strong>New Estimate</strong>. Give it a name (e.g., "Cost Estimate v1") and optionally choose a template. The BOQ editor opens with an empty grid ready for your first position.</p>

<h3 id="fs-position">Step 5: Add Positions</h3>
<p>In the BOQ editor, click <strong>Add Position</strong> or press Enter on an empty row. Fill in:</p>
<ul>
<li><strong>Ordinal</strong> &mdash; Position number (e.g., "01.001")</li>
<li><strong>Description</strong> &mdash; What work is being done (e.g., "Reinforced concrete C30/37 for foundation slab")</li>
<li><strong>Unit</strong> &mdash; Measurement unit (m3, m2, m, kg, pcs, lsum)</li>
<li><strong>Quantity</strong> &mdash; How much (e.g., 86.4)</li>
<li><strong>Unit Rate</strong> &mdash; Price per unit (e.g., 295.00 EUR)</li>
</ul>
<p>The <strong>Total</strong> column calculates automatically (Quantity x Unit Rate). You can also search the cost database by clicking the database icon next to any position to find and apply a rate from the 55,000+ CWICR items.</p>
</section>

<section id="install">'''

html = html.replace(overview_end, projects_section)
print("Added First Steps section")


# === 2. EXPAND BOQ Editor with detailed workflows ===

boq_shortcuts = '<h3 id="boq-shortcuts">Keyboard Shortcuts</h3>'
boq_extra = '''<h3 id="boq-sections">Working with Sections</h3>
<p>Sections organize your BOQ into logical groups (e.g., "300 Structure", "400 HVAC"). To create a section:</p>
<ol>
<li>Click <strong>Add Section</strong> in the toolbar</li>
<li>Enter the section name and optional DIN 276/NRM classification code</li>
<li>All positions added after a section header belong to that section</li>
<li>Each section shows its own subtotal at the bottom</li>
</ol>
<p>You can collapse/expand sections to focus on specific trades. Drag sections to reorder the entire BOQ structure.</p>

<h3 id="boq-resources">Linking Resources</h3>
<p>Each BOQ position can have linked resources that break down the unit rate into components:</p>
<ul>
<li><strong>Materials</strong> &mdash; Concrete, steel, bricks, insulation (from Resource Catalog)</li>
<li><strong>Labor</strong> &mdash; Worker hours by trade (formworker, electrician, plumber)</li>
<li><strong>Equipment</strong> &mdash; Crane hours, excavator, concrete pump</li>
</ul>
<p>To add resources: expand a position row, click "Add Resource", search the catalog, set the quantity factor (e.g., 120 kg rebar per m3 concrete). The position unit rate updates automatically from the sum of its resources.</p>

<h3 id="boq-markups">Configuring Markups</h3>
<p>Markups are applied after the net total (sum of all positions). Common markups include:</p>
<ul>
<li><strong>Overhead</strong> &mdash; Company overhead costs (typically 8-15%)</li>
<li><strong>Profit</strong> &mdash; Contractor profit margin (typically 5-12%)</li>
<li><strong>Contingency</strong> &mdash; Risk reserve for unforeseen costs (typically 5-10%)</li>
<li><strong>VAT/Tax</strong> &mdash; Value Added Tax (19% in Germany, 20% in UK, varies by country)</li>
</ul>
<p>Click <strong>Add Markup</strong> in the toolbar. You can set regional defaults or customize per project. Markups can be percentage-based or fixed amounts, and they compound in order (overhead first, then profit on the overhead-inclusive amount, then VAT on the total).</p>

<h3 id="boq-validation-detail">Running Validation</h3>
<p>Press <strong>Ctrl+Shift+V</strong> or click the shield icon in the toolbar to run validation. The system checks your BOQ against the selected rule sets and shows results inline:</p>
<ul>
<li>Positions with errors get a red dot</li>
<li>Positions with warnings get a yellow dot</li>
<li>The validation score (%) appears in the toolbar</li>
<li>Click any dot to see the specific issue and fix it</li>
</ul>

<h3 id="boq-import-detail">Importing Data</h3>
<p>The BOQ editor supports importing from multiple sources:</p>
<ul>
<li><strong>Excel/CSV</strong> &mdash; Click Import, select your file. The wizard maps your columns (description, quantity, unit, rate) to BOQ fields. Preview before committing.</li>
<li><strong>GAEB XML</strong> &mdash; Import German-standard tender files directly. Positions, sections, and rates are preserved.</li>
<li><strong>Paste from clipboard</strong> &mdash; Copy rows from Excel, click "Paste" in the toolbar. The system detects columns automatically.</li>
<li><strong>AI Smart Import</strong> &mdash; Upload any PDF, photo, or CAD file. AI extracts BOQ positions with quantities and rates.</li>
</ul>

''' + boq_shortcuts

html = html.replace(boq_shortcuts, boq_extra)
print("Expanded BOQ Editor section")


# === 3. EXPAND Cost Database with usage instructions ===

costs_vector = '<h3 id="costs-vector">Vector Search'
costs_extra = '''<h3 id="costs-howto">How to Use the Cost Database</h3>
<p>The cost database is designed for two main workflows:</p>

<h4>Workflow A: Browse and Apply to BOQ</h4>
<ol>
<li>Navigate to <strong>Databases &rarr; Cost Database</strong></li>
<li>Select your region tab (e.g., "Germany / DACH")</li>
<li>Search for a cost item by typing in the search bar (e.g., "concrete foundation")</li>
<li>Click the star icon to add frequently used items to your Favorites</li>
<li>In the BOQ editor, click the database icon next to any position to search and apply a rate</li>
</ol>

<h4>Workflow B: Import Your Own Database</h4>
<ol>
<li>Navigate to <strong>Databases &rarr; Cost Database &rarr; Import Database</strong></li>
<li>Prepare an Excel or CSV file with columns: Code, Description, Unit, Rate, Currency</li>
<li>Upload the file and map columns in the import wizard</li>
<li>Preview the data before committing</li>
<li>Your imported items appear alongside CWICR data with your custom source tag</li>
</ol>

<h4>Understanding Cost Item Structure</h4>
<p>Each cost item contains:</p>
<ul>
<li><strong>Code</strong> &mdash; Unique identifier (e.g., KADX_KAME_KAKAME_KAME)</li>
<li><strong>Description</strong> &mdash; Work item name in up to 9 languages</li>
<li><strong>Unit</strong> &mdash; Unit of measurement (m2, m3, t, pcs, etc.)</li>
<li><strong>Rate</strong> &mdash; Price per unit in the regional currency</li>
<li><strong>Components</strong> &mdash; Breakdown into materials, labor, equipment (when available)</li>
<li><strong>Classification</strong> &mdash; DIN 276, NRM, MasterFormat codes for cross-referencing</li>
</ul>

''' + costs_vector

html = html.replace(costs_vector, costs_extra)
print("Expanded Cost Database section")


# === 4. EXPAND AI section with detailed workflows ===

ai_advisor_marker = '<h3 id="ai-advisor">AI Cost Advisor</h3>'
ai_extra = '''<h3 id="ai-setup">Setting Up AI</h3>
<p>Before using AI features, you need to configure an API key:</p>
<ol>
<li>Go to <strong>Settings &rarr; AI Configuration</strong></li>
<li>Choose your provider (Anthropic Claude recommended for best accuracy)</li>
<li>Paste your API key (get one from your provider\'s website)</li>
<li>Click <strong>Test Connection</strong> to verify it works</li>
<li>Click <strong>Save Settings</strong></li>
</ol>
<p>Your API key is stored encrypted on your server and never sent anywhere except to the provider you selected. AI features are completely optional &mdash; the platform works fully without them.</p>

<h3 id="ai-text-workflow">Text Estimation: Step by Step</h3>
<ol>
<li>Navigate to <strong>Takeoff &rarr; AI Estimate</strong></li>
<li>Select the <strong>Text</strong> tab</li>
<li>Describe your project in the text area. Be specific about: building type, floor area, number of floors, structural system, location. Example: "5-story residential building, 3000 m2 GFA, reinforced concrete frame, brick facade, flat roof, Berlin"</li>
<li>Set Location, Currency, and Standard (or leave as Auto)</li>
<li>Click <strong>Generate Estimate</strong></li>
<li>Wait 10-20 seconds while AI processes your description</li>
<li>Review the generated BOQ items &mdash; each shows ordinal, description, unit, quantity, unit rate, and total</li>
<li>Click <strong>Save as BOQ</strong> to create a real BOQ from the estimate, or <strong>Match with Cost DB</strong> to replace AI rates with real market prices from CWICR</li>
</ol>

<h3 id="ai-photo-workflow">Photo Estimation</h3>
<p>Upload a building photo and AI identifies structural elements, estimates dimensions from visible scale references (doors ~0.9m, floor height ~3m), and generates BOQ items. Works best with clear exterior photos showing the full building.</p>

<h3 id="ai-cad-workflow">CAD/BIM Estimation</h3>
<p>Upload a Revit, IFC, DWG, or DGN file. The system extracts elements with volumes and areas using DDC converters, then AI maps them to construction work items with pricing. This combines exact quantities from the model with AI-suggested rates.</p>

''' + ai_advisor_marker

html = html.replace(ai_advisor_marker, ai_extra)
print("Expanded AI section")


# === 5. EXPAND Takeoff section ===

takeoff_qto = '<h3 id="takeoff-qto'
takeoff_extra = '''<h3 id="takeoff-workflow">CAD/BIM Takeoff: Step by Step</h3>
<ol>
<li>Navigate to <strong>Takeoff &rarr; CAD/BIM Takeoff</strong></li>
<li>Drag and drop your CAD/BIM file (.rvt, .ifc, .dwg, .dgn) onto the upload area</li>
<li>Wait for the DDC converter to extract elements (30-60 seconds for typical files)</li>
<li>The system shows available columns and suggests grouping presets:
  <ul>
  <li><strong>Standard Revit QTO</strong> &mdash; Group by Category + Type Name, sum Volume/Area/Count</li>
  <li><strong>Detailed</strong> &mdash; Add Level for per-floor breakdown</li>
  <li><strong>By Family</strong> &mdash; Group by Revit Family for procurement lists</li>
  <li><strong>Custom</strong> &mdash; Choose any combination of the 1200+ extracted columns</li>
  </ul>
</li>
<li>Click <strong>Apply Grouping</strong> to see the quantity table</li>
<li>Review the grouped results &mdash; filter out empty groups, delete irrelevant categories, sort by volume</li>
<li>Click <strong>Save as BOQ</strong> to transfer quantities to a Bill of Quantities for pricing</li>
</ol>

<h3 id="takeoff-pdf-workflow">PDF Takeoff: Step by Step</h3>
<ol>
<li>Navigate to <strong>Takeoff &rarr; PDF Takeoff</strong></li>
<li>Upload your PDF construction drawing</li>
<li>The system extracts text and tables from the PDF automatically</li>
<li>Click <strong>Analyze with AI</strong> to extract construction elements with quantities</li>
<li>Or switch to the <strong>Measurements</strong> tab for manual takeoff:
  <ul>
  <li>Set the drawing scale (click two known points and enter the real distance, or select a preset like 1:100)</li>
  <li>Select <strong>Distance</strong> tool and click two points to measure length</li>
  <li>Select <strong>Area</strong> tool and click corners of a polygon to measure area</li>
  <li>Select <strong>Count</strong> tool and click on elements to count them</li>
  </ul>
</li>
<li>All measurements are saved and can be exported to a BOQ</li>
</ol>

''' + takeoff_qto

html = html.replace(takeoff_qto, takeoff_extra)
print("Expanded Takeoff section")


# === 6. EXPAND Settings ===

settings_env = '<h3 id="env-vars">Environment Variables</h3>'
settings_extra = '''<h3 id="settings-profile">Profile Settings</h3>
<p>Update your display name, email, and password. Choose between <strong>Simple</strong> mode (essential tools only) and <strong>Advanced</strong> mode (all modules visible including risk, tendering, analytics).</p>

<h3 id="settings-ai">AI Configuration</h3>
<p>Select your preferred AI provider and enter the API key. The system supports 7 providers:</p>
<ul>
<li><strong>Anthropic Claude</strong> (recommended) &mdash; Best accuracy for construction estimation. Get key at console.anthropic.com</li>
<li><strong>OpenAI GPT-4o</strong> &mdash; Strong general-purpose model with vision. Get key at platform.openai.com</li>
<li><strong>Google Gemini</strong> &mdash; Free tier available. Get key at aistudio.google.com</li>
<li><strong>OpenRouter</strong> &mdash; Access any model through one API key. Get key at openrouter.ai</li>
<li><strong>Mistral, Groq, DeepSeek</strong> &mdash; Additional options for specific needs</li>
</ul>
<p>Click <strong>Test Connection</strong> after entering your key to verify it works before saving.</p>

<h3 id="settings-modules">Module Configuration</h3>
<p>Enable or disable individual modules from Settings &rarr; Modules. You can install additional modules from the Module Marketplace including regional standards, converters, and analytics tools.</p>

<h3 id="settings-language">Language &amp; Regional Settings</h3>
<p>Change your interface language at any time from the language selector in the header. The system supports 21 languages including right-to-left (Arabic). Regional settings affect date formats, number formatting, and default classification standards.</p>

<h3 id="settings-backup">Backup &amp; Restore</h3>
<p>Export your entire database as a backup file (JSON format). This includes all projects, BOQs, positions, settings, and user data. Restore from a backup file to recover data or migrate to a new server.</p>

''' + settings_env

html = html.replace(settings_env, settings_extra)
print("Expanded Settings section")


open('docs/docs.html', 'w', encoding='utf-8').write(html)
print(f'\nFinal size: {len(html)} bytes ({len(html)//1024} KB)')
print(f'Sections: {html.count("<section")}')
print(f'H3 headings: {html.count("<h3")}')
