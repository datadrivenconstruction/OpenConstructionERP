"""Expand docs.html with detailed module documentation."""
import re

html = open('docs/docs.html', encoding='utf-8').read()

# Add sidebar entries for new sections
old_sidebar_planning = '<div class="sb-sec">\n    <div class="sb-t">PLANNING</div>'
new_sidebar = '''<div class="sb-sec">
    <div class="sb-t">PLANNING</div>
    <a href="#planning" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="4" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg> 4D Schedule</a>
    <a href="#costmodel-detail" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg> 5D Cost Model</a>
  </div>
  <div class="sb-sec">
    <div class="sb-t">PROCUREMENT</div>
    <a href="#tendering" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect width="8" height="4" x="8" y="2" rx="1"/></svg> Tendering</a>
    <a href="#changeorders-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg> Change Orders</a>
    <a href="#risk-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg> Risk Register</a>
  </div>
  <div class="sb-sec">
    <div class="sb-t">TOOLS</div>
    <a href="#validation-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> Validation</a>
    <a href="#reports-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/></svg> Reports</a>
    <a href="#documents-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"/><polyline points="14 2 14 8 20 8"/><path d="m3 15 2 2 4-4"/></svg> Documents</a>
    <a href="#analytics-section" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="18" x2="18" y1="20" y2="10"/><line x1="12" x2="12" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="14"/></svg> Analytics</a>'''

# Remove old planning sidebar section that has duplicate 4D/5D entries
old_planning_sidebar = '''<div class="sb-sec">
    <div class="sb-t">PLANNING</div>
    <a href="#planning" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="4" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg> 4D Schedule</a>
    <a href="#planning" class="sb-a"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg> 5D Cost Model</a>
  </div>'''

if old_planning_sidebar in html:
    html = html.replace(old_planning_sidebar, new_sidebar)
    print("Replaced planning sidebar with expanded version")
else:
    print("Old planning sidebar not found, trying alternate")
    # Try simpler match
    html = html.replace(
        '<div class="sb-t">PLANNING</div>',
        '<div class="sb-t">PLANNING</div>\n  </div>\n  <div class="sb-sec">\n    <div class="sb-t">PROCUREMENT</div>'
    )

# Now expand the Planning section content
old_plan = '<section id="planning"><h2>4D Schedule &amp; 5D Cost Model</h2><ul>'
new_plan_start = '''<section id="planning"><h2>4D Schedule &amp; 5D Cost Model</h2>
<p>Plan your construction project timeline and track costs over time with integrated scheduling and financial modeling tools.</p>

<h3 id="schedule-detail">4D Schedule</h3>
<p>The scheduling module provides a professional Gantt chart for managing your construction timeline. Create activities, set durations, define dependencies, and the system automatically calculates the critical path showing which activities must not be delayed.</p>
<ul>
<li><strong>Activity types</strong> &mdash; Tasks, milestones, and summary activities with WBS codes for structured breakdown</li>
<li><strong>Dependencies</strong> &mdash; Finish-to-Start (FS), Start-to-Start (SS), Finish-to-Finish (FF), and Start-to-Finish (SF) relationships between activities</li>
<li><strong>Critical path</strong> &mdash; Automatic CPM calculation with visual highlighting. Activities on the critical path are marked with a "CP" badge</li>
<li><strong>Auto-generate from BOQ</strong> &mdash; Select a BOQ and set total project duration. The system creates one activity per section with cost-proportional durations and sequential dependencies</li>
<li><strong>Progress tracking</strong> &mdash; Update activity status (completed/in-progress/pending) and track actual vs planned dates</li>
<li><strong>Monte Carlo simulation</strong> &mdash; Run probabilistic analysis with optimistic/pessimistic ranges to get risk-adjusted completion dates with confidence levels</li>
</ul>

<h3 id="costmodel-detail">5D Cost Model</h3>
<p>The cost model connects your BOQ data to the project timeline, giving you a time-phased view of construction costs with Earned Value Management metrics.</p>
<ul>'''

if old_plan in html:
    html = html.replace(old_plan, new_plan_start)
    print("Expanded planning section")

# Add new sections before settings
settings_marker = '<section id="settings">'

new_modules = '''<section id="tendering">
<h2>Tendering &amp; Bid Management</h2>
<p>Manage the complete procurement workflow from creating bid packages to comparing proposals and awarding contracts to subcontractors.</p>
<h3 id="tender-create">Creating a Tender Package</h3>
<p>Navigate to Procurement, select a project, and click "Create Package". Specify the package name, scope description, submission deadline, and select which BOQ positions to include. You can create multiple packages per project (e.g., structural works, MEP, finishing).</p>
<h3 id="tender-bids">Managing Bids</h3>
<p>Add bids from subcontractors with company name, contact details, and quoted prices for each BOQ position. The system supports multiple bids per package for side-by-side comparison.</p>
<h3 id="tender-compare">Bid Comparison</h3>
<p>The price mirror shows all bids in a comparison table with unit rates and totals per position. Visual indicators highlight the lowest and highest bids. Export the comparison as CSV for stakeholder review.</p>
<h3 id="tender-award">Award Process</h3>
<p>Mark the winning bid with the Award button and add justification notes. Package status tracks through: Draft, Issued, Collecting, Evaluating, Awarded, Closed.</p>
</section>

<section id="risk-section">
<h2>Risk Register</h2>
<p>Identify, assess, and manage project risks using a probability-impact matrix. Quantify risk exposure and plan mitigation strategies for each identified risk.</p>
<h3 id="risk-matrix">Risk Assessment Matrix</h3>
<p>The matrix displays all risks on a probability (0.1-0.9) vs impact (low/medium/high/critical) grid with color coding. Each risk shows its calculated exposure score (probability multiplied by impact cost).</p>
<h3 id="risk-manage">Managing Risks</h3>
<p>For each risk, document: unique code (R-001), title, category (technical, financial, schedule, regulatory, environmental, safety), mitigation strategy, contingency plan, risk owner, cost impact, and schedule impact in days. Track status through: Identified, Assessed, Mitigating, Closed, or Occurred.</p>
</section>

<section id="changeorders-section">
<h2>Change Orders</h2>
<p>Track scope changes and their impact on project cost and schedule. Change orders provide an audit trail of all modifications made after the initial estimate.</p>
<h3 id="co-workflow">Change Order Workflow</h3>
<p>Create a change order with code (CO-001), title, and reason category (client request, design change, unforeseen condition, regulatory). Add line items specifying affected BOQ positions with original and new quantities/rates. The system calculates cost deltas automatically. Status moves through: Draft, Submitted, Under Review, Approved/Rejected.</p>
</section>

<section id="validation-section">
<h2>Validation &amp; Quality Checks</h2>
<p>Run automated quality checks on your BOQs to catch errors before they become problems. The validation engine applies 42 configurable rules against your estimate data.</p>
<h3 id="val-rules">Rule Sets</h3>
<ul>
<li><strong>BOQ Quality</strong> &mdash; Missing quantities, zero prices, duplicate positions, unrealistic unit rates, empty descriptions</li>
<li><strong>DIN 276 Compliance</strong> &mdash; Cost group hierarchy, required KG codes, completeness per level</li>
<li><strong>GAEB Format</strong> &mdash; Structure validation for GAEB XML export (X83)</li>
<li><strong>NRM Compliance</strong> &mdash; NRM 1/2 element structure and measurement rules</li>
<li><strong>MasterFormat</strong> &mdash; CSI division structure and code format</li>
</ul>
<h3 id="val-results">Understanding Results</h3>
<p>Each validation produces a quality score (0-100%) with color-coded findings: Errors (red, must fix), Warnings (yellow, should review), Info (blue, suggestions). Click any finding to navigate directly to the affected BOQ position.</p>
</section>

<section id="reports-section">
<h2>Reports &amp; Export</h2>
<p>Generate professional documents from your project data for stakeholders, clients, and regulatory compliance.</p>
<ul>
<li><strong>BOQ Report (PDF)</strong> &mdash; Complete Bill of Quantities with sections, positions, subtotals, markups, and grand total</li>
<li><strong>BOQ Export (Excel)</strong> &mdash; Full data in .xlsx with formulas, formatting, and section grouping</li>
<li><strong>Cost Report (PDF)</strong> &mdash; Summary by trade, category, or classification standard</li>
<li><strong>GAEB XML (X83)</strong> &mdash; Standard German/Austrian tender format for electronic submission</li>
<li><strong>CSV Export</strong> &mdash; Raw data for import into other tools or spreadsheets</li>
</ul>
</section>

<section id="documents-section">
<h2>Document Management</h2>
<p>Centralize all project documents. Upload drawings, contracts, specifications, and photos with automatic categorization and search.</p>
<ul>
<li><strong>Upload</strong> &mdash; Drag and drop files up to 100 MB (PDF, images, Office, CAD)</li>
<li><strong>Categories</strong> &mdash; Drawings, contracts, specifications, photos, correspondence</li>
<li><strong>Tags</strong> &mdash; Custom tags for flexible filtering</li>
<li><strong>Preview</strong> &mdash; View PDFs and images directly in the browser</li>
<li><strong>Version tracking</strong> &mdash; Upload dates, file sizes, uploader identity</li>
</ul>
</section>

<section id="analytics-section">
<h2>Analytics Dashboard</h2>
<p>View cross-project budget performance. The dashboard aggregates financial data across all projects to identify trends, variances, and at-risk budgets.</p>
<ul>
<li><strong>Project table</strong> &mdash; Sortable list: budget, actual spend, variance, percentage, status</li>
<li><strong>KPI cards</strong> &mdash; Total portfolio value, average variance, projects on/over budget</li>
<li><strong>Regional filter</strong> &mdash; Compare performance across markets (DACH, UK, US, Gulf)</li>
<li><strong>Status filter</strong> &mdash; Focus on over-budget projects for attention</li>
</ul>
</section>

'''

html = html.replace(settings_marker, new_modules + settings_marker)
print("Added 7 new module sections")

open('docs/docs.html', 'w', encoding='utf-8').write(html)
print(f'Final: {len(html)} bytes')
