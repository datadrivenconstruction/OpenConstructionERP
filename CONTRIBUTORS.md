# Contributors

OpenConstructionERP is authored and owned by DataDrivenConstruction (see
[AUTHORS.md](AUTHORS.md)). The people listed here are contributors: they have sent bug
reports, questions, ideas and patches that made the project better. They are not authors
of the project, and authorship and copyright remain with DataDrivenConstruction.

Thank you to everyone who has contributed.

Being listed here means one thing: you reported a bug, asked a question, proposed an idea
or sent a patch, and the project is better for it. It does not mean that any of your code
is in the product. We do not merge external pull requests. When a fix arrives as a patch
we read it, credit the author, and write our own implementation from scratch. That keeps
one reviewed source of truth for a codebase that many companies run in production, and it
avoids taking in code we have not written ourselves, which is the safer path on security.
So every credit below is for the report, the question or the proposal, and the
implementation is our own.

- **skolodi** ([@skolodi](https://github.com/skolodi)): issue reports and field feedback
  on the BOQ AI assistant, and reported that a single budget could mix currencies and that
  an exchange rate could be entered the wrong way round
  ([#111](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/111)).
- **Mourtadha Diop** ([@Mourdi59](https://github.com/Mourdi59)): sent a pull request
  proposing fixes for three BIM viewer bugs
  ([#159](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/159)),
  COLLADA namespace-prefix serialisation in `ifc_processor`, defence-in-depth regex
  tolerance in `ElementManager`, and `degraded` model status surfacing in the viewer UI;
  the shipped implementation is our own. Later raised ideas for driving BOQ quantities from live BIM parameters, surfacing real
  server errors on Excel paste, and resolving linked elements per model in multi-model
  setups ([#206](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/206)).
  More recently proposed BOQ per-element quantity formulas with a projection editor and a
  batch of multi-model BIM viewer fixes
  ([#347](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/347)), and a
  schedule dependency editor, an editable activity data grid and a per-activity work
  calendar for the Gantt
  ([#348](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/348)). Both
  shipped as our own implementation.
- **rjohny** ([@rjohny55](https://github.com/rjohny55)): sent a multi-area pull request
  ([#161](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/161))
  proposing defensive guards for the slow-query SQLAlchemy listener and the
  module-presence probe under concurrency, a FieldReport activity-rollup column fix,
  Qdrant multipart snapshot upload so app-container snapshots reach a separate Qdrant
  container, and three new AI providers, Kimi (Moonshot AI), Ollama and vLLM, with custom
  base URL support for the two local backends. The shipped implementation is our own.
- **Jehad Baniowda** ([@jehadbaniodeh](https://github.com/jehadbaniodeh)): sent five pull
  requests proposing fixes to the production Docker deployment and the takeoff viewer:
  that the backend image install its dependencies and start correctly
  ([#173](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/173)), that
  nginx upgrade WebSocket connections so real-time notifications and presence work
  ([#176](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/176)), that
  `.mjs` workers be served with the correct MIME type so the PDF takeoff viewer renders
  ([#175](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/175)), that
  the upload ceiling be raised to 100M for PDF and CAD drawings
  ([#174](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/174)), and
  that takeoff documents open in the in-app viewer instead of a broken download navigation
  ([#172](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/172)). The
  shipped implementation is our own.
- **Jérémy Christillin** ([@bvisible](https://github.com/bvisible)): feedback and feature
  proposals for the PDF takeoff module, in-canvas measurement editing and LLM-assisted
  plan reading
  ([#194](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/194)).
- **mohandshamada** ([@mohandshamada](https://github.com/mohandshamada)): issue reports and
  proposals on the converters version-check payload shape
  ([#195](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/195),
  [#196](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/196)), IFC
  zero-elements processing ([#197](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/197)),
  BIM empty-state and upload messaging
  ([#198](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/198)), and
  resumable CAD uploads ([#199](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/199)).
- **leval907** ([@leval907](https://github.com/leval907)): flagged that qdrant-client removed
  its `.search()` API and that the remaining call sites needed migrating to `query_points()`
  ([#201](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/201)).
- **alikhalilx** ([@alikhalilx](https://github.com/alikhalilx)): reported that ERP Chat
  rendered Markdown tables as raw pipe text and pointed at the hand-rolled chat renderers
  ([#224](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/224)), that
  the sidebar greyed out company-wide modules such as CRM and subcontractors even when they
  already held data
  ([#228](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/228)), and
  that the pinned-item tooltip showed a raw placeholder instead of the module name
  ([#229](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/229)).
- **arvildev** ([@arvildev](https://github.com/arvildev)): pointed out that the required
  `POSTGRES_PASSWORD` and `JWT_SECRET` interpolations in the quickstart Docker Compose file
  needed quoting so the YAML parses before the fail-fast checks run
  ([#227](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/227)). Later
  reported three PDF takeoff viewer bugs: the scale-calibrate button showing its full tooltip
  text as its visible label, the draw-tool previews not being suppressed during a two-click
  scale calibration and lingering after it, and the toolbar top row wrapping when the side
  panels narrow it
  ([#366](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/366),
  [#367](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/367),
  [#368](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/368)).
- **Aidan Koetaan** ([@aidankoetaan-tech](https://github.com/aidankoetaan-tech),
  akoetaan@cut.ac.za): proposed a South Africa construction pack and shared a reference
  implementation covering SANS 1200 and ASAQS measurement, CIDB contractor grading, the
  PPPFA 80/20 and 90/10 procurement scoring, infrastructure delivery gates and ZAR VAT. The
  shipped South Africa pack is our own implementation, written from the public standards.
- **expalex1507** ([@expalex1507](https://github.com/expalex1507)): reported that the Docker
  quickstart failed across the Dockerfile, pyproject, the first migration and some missing
  dependencies ([#26](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/26)).
- **consigcody94** ([@consigcody94](https://github.com/consigcody94)): flagged that a
  hardcoded JWT secret default could let tokens be forged in production
  ([#27](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/27)).
- **migfrazao2003** ([@migfrazao2003](https://github.com/migfrazao2003)): reported that
  `make quickstart` failed on frontend TypeScript build errors
  ([#42](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/42)) and that
  the BIM viewer drew geometry that did not match the original IFC model
  ([#53](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/53)).
- **maher00746** ([@maher00746](https://github.com/maher00746)): asked about pricing data
  sources ([#44](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/44))
  and proposed real-time collaboration
  ([#51](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/51)).
- **rrvizuete** ([@rrvizuete](https://github.com/rrvizuete)): reported an error rendering an
  IFC file exported from Civil software
  ([#52](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/52)).
- **candcconsulting** ([@candcconsulting](https://github.com/candcconsulting)): asked how to
  enable a CWICR-style catalog for a UAE sample
  ([#79](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/79)).
- **rashidengg-arch** ([@rashidengg-arch](https://github.com/rashidengg-arch)): an early bug
  report during testing
  ([#87](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/87)).
- **hungdd84** ([@hungdd84](https://github.com/hungdd84)): reported that setting a Gemini API
  key failed because the model id was out of date
  ([#103](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/103)).
- **mkozjak** ([@mkozjak](https://github.com/mkozjak)): reported that the DWG takeoff upload
  button did not work
  ([#110](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/110)).
- **ChristianSantoro** ([@ChristianSantoro](https://github.com/ChristianSantoro)): reported
  that IFC and RVT files would not open in the 3D viewer
  ([#113](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/113),
  [#115](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/115)).
- **online14230** ([@online14230](https://github.com/online14230)): proposed regional data
  support ([#116](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/116)).
- **DevpratikDevelopers** ([@DevpratikDevelopers](https://github.com/DevpratikDevelopers)):
  reported a `p.data.filter is not a function` crash
  ([#122](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/122)).
- **hanisedawy** ([@hanisedawy](https://github.com/hanisedawy)): sent in-app bug reports that
  helped surface viewer and upload issues
  ([#123](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/123),
  [#124](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/124)).
- **sergeilapp** ([@sergeilapp](https://github.com/sergeilapp)): proposed an incoming webhook
  leads module ([#147](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/147)).
- **jyloveqq** ([@jyloveqq](https://github.com/jyloveqq)): reported that the app could not
  install on their setup
  ([#154](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/154)), that
  Match Elements showed no catalogs loaded
  ([#162](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/162)), that the
  indexed vector count did not change after an import
  ([#170](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/170)) and that
  importing a cost database could crash the app
  ([#171](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/171)).
- **JORBDAAG** ([@JORBDAAG](https://github.com/JORBDAAG)): reported BIM viewer problems through
  the in-app reporter
  ([#167](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/167),
  [#168](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/168)).
- **thiemotorres** ([@thiemotorres](https://github.com/thiemotorres)): reported that
  `make quickstart` served only 404s because of a broken SPA fallback handler, and flagged
  stale project names, hardcoded local paths and wrong GitHub links across the docs
  ([#48](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/48)).
- **braedonsaunders** ([@braedonsaunders](https://github.com/braedonsaunders)): traced CWICR
  cost-database imports failing on PostgreSQL to the importer always deriving a SQLite path and
  connection regardless of the configured backend, so a Docker quickstart against Postgres
  downloaded a catalog and then failed at insert time
  ([#107](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/107)).
- **gbatkhuyag** ([@gbatkhuyag](https://github.com/gbatkhuyag)): proposed and drafted Mongolian
  (`mn`) language support across the backend and frontend, which led to the Mongolian locale the
  app now ships
  ([#125](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/125),
  [#137](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/137)).
- **EQSTLab** ([@EQSTLab](https://github.com/EQSTLab)): reported through a private security
  advisory that the in-app upgrade endpoint ran without authentication, so anyone who could
  reach the API on a quickstart or an exposed install could force a package reinstall or a
  downgrade. The fix, which gates the endpoint behind an authenticated admin, is our own.
- **nullbenny** ([@nullbenny](https://github.com/nullbenny)): reported through a private
  security advisory a blind server-side request forgery in the configurable self-hosted AI
  provider endpoint, where a saved Ollama or vLLM base URL was fetched server-side without
  validation. Our own fix checks the URL when it is saved and again after DNS resolution at
  dispatch, always blocking link-local and cloud-metadata addresses while keeping loopback and
  private hosts reachable for a local runtime, with an optional allowlist.
- **dizconnectz** ([@dizconnectz](https://github.com/dizconnectz)): reported through a private
  security advisory a cross-tenant access gap where a project handover document bundle could be
  read by another tenant. We closed it with an ownership check on the handover chain.
- **sa05e60** ([@sa05e60](https://github.com/sa05e60)): reported through a private security
  advisory that one user's own self-hosted AI provider setting could outlive the request that
  set it and then apply to other people served by the same process, so a second user's project
  data could be sent to a host they never chose. Our own fix keeps that setting to a single
  request.

- **buzzy84** ([@buzzy84](https://github.com/buzzy84)): asked for a client Excel round-trip
  that returns a completed bill in the original workbook with its sheets, styles and formulas
  intact ([#360](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/360)), and for parametric assemblies whose child lines are driven by user-defined
  parameters ([#365](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/365)).
- **masc145** ([@masc145](https://github.com/masc145)): reported that the Docker quickstart
  build dies in `npm ci` during the frontend stage, and reproduced it again from a clean clone
  after the first fix ([#404](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/404)).
- **arq-migfrazao** ([@arq-migfrazao](https://github.com/arq-migfrazao)): reported that the
  Windows desktop app cannot install its own updates, because the upgrade path called the CLI
  with a subcommand the CLI does not accept ([#403](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/403)).
- **Colin TAN** ([@colintanlk](https://github.com/colintanlk)): reported that after upgrading
  to 12.6.0 the vector service was no longer running and would not install from the prompt, on
  a page that also threw a number-formatting error ([#391](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/391)).
- **Ronald Munjoma** ([@ronna](https://github.com/ronna)): reported that the application did
  not start after a Windows 11 upgrade ([#317](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/317)).
- **erfan** ([@rfwn](https://github.com/rfwn)): asked where to start when adding a region's
  locale, currency, classifications and translation keys, and found no guide anywhere in the
  codebase, the docs or the repo, which is a documentation gap we accepted ([#388](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/388)).
- **Yusuke Hayashi** ([@yhay81](https://github.com/yhay81)): answered that question in detail,
  covering both the partner pack route and the fork route, and in doing so found that the
  "auto-generated, do not edit by hand" banner on the English locale file is stale residue,
  because the per-locale files are the source of truth now and the splitter script is a spent
  one-off ([#388](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/388)).
- **Aganin Vadim** ([@aganinvadim1-commits](https://github.com/aganinvadim1-commits)): asked
  whether authorisation through Keycloak is planned, which surfaced that there is no OIDC, SAML
  or LDAP path at all ([#363](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/363)).
- **ravindrakumar2053-bit**
  ([@ravindrakumar2053-bit](https://github.com/ravindrakumar2053-bit)): asked for localised
  estimating with separate length, breadth, depth and quantity columns, a measurement book as
  its own record with status and history, site profit and loss, and bar bending schedules
  generated from a drawing ([#352](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/352)).
- **hibohsuc-svg** ([@hibohsuc-svg](https://github.com/hibohsuc-svg)): reported that a DWG
  revision could not be uploaded for comparison, because compare only worked between two
  versions of a single drawing, which led to drawing against drawing compare ([#289](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/289)).
- **Simon** ([@SimonOhli](https://github.com/SimonOhli)): independently reproduced the v10.1.0
  backend startup failure through a Docker and Portainer upgrade from the published image,
  which confirmed the fault was not local to the original reporter ([#322](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/322)).
- **Temael Belzi** ([@Tigercatman](https://github.com/Tigercatman)): ten reports across
  document management, the client portal, project archiving and coordination, including a
  project that could not be found, model conversion failing, and notification titles and
  bodies rendering incorrectly ([#271](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/271), [#288](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/288), [#361](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/361)).
- **darkleono** ([@darkleono](https://github.com/darkleono)): reported a migration that assumed
  SQLite syntax and so crashed under PostgreSQL ([#295](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/295)), a regional pack shipped without its
  compliance entry in the contracts registry ([#305](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/305)), two different words used for the same
  document in Mexican Spanish ([#304](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/304)), and header and widget overlap plus date timezone
  shifts ([#293](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/293), [#294](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/294)).
- **Mr.R** ([@Mr-OpenR](https://github.com/Mr-OpenR)): reported that the Files page failed on a
  401 from the user preferences endpoint ([#340](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/340)).
- **Gerard T** ([@serviteur](https://github.com/serviteur)): proposed tracking the sixth,
  seventh and eighth dimensions of a model and widening 3D ingestion to mesh formats ([#296](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/296)).
- **j209** ([@j209](https://github.com/j209)): reported a parsing error in the 3D viewer on a
  sample mechanical model ([#291](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/291)).
- **MeCode4** ([@MeCode4](https://github.com/MeCode4)): reported that the dashboard failed on a
  500 from the projects list endpoint ([#278](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/278)).
- **skeltic-wq** ([@skeltic-wq](https://github.com/skeltic-wq)): reported a network error on
  the AI settings tab ([#244](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/244)).
- **Nebulasunrise-OG** ([@Nebulasunrise-OG](https://github.com/Nebulasunrise-OG)): asked for
  inline preview of files referenced from transmittals, inspections and non-conformance
  records, and for files to be linkable from further sections, both of which shipped in v9.2.0
  ([#246](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/246)).
- **cosanostra** ([@cosanostratr](https://github.com/cosanostratr)): sent a pull request
  proposing an LED display management module
  ([#97](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/97)).
- **MEEGOO** ([@mahabdalla](https://github.com/mahabdalla)): sent a pull request carrying
  changes from their fork
  ([#108](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/108)).
- **Abi Paudel** ([@abipaudel](https://github.com/abipaudel)): sent two pull requests
  proposing a Dockerfile for a Node.js setup at the repository root
  ([#329](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/329),
  [#330](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/330)).
- **INAPA-desarrolloTIC** ([@INAPA-desarrolloTIC](https://github.com/INAPA-desarrolloTIC)):
  sent a pull request proposing API key authentication on the inbound capture webhook
  endpoints, so a headless caller no longer needs a login and refresh cycle
  ([#331](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/331)). The
  shipped implementation is our own.
- **Ali Sadikin Ma** ([@alisadikinma](https://github.com/alisadikinma)): sent a pull request
  proposing an Indonesian AHSP unit price analysis module
  ([#345](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/345)).
- **ziadeh** ([@ziadeh](https://github.com/ziadeh)): sent a pull request proposing a schedule
  intelligence module with a locked-figure guard and a readiness engine
  ([#362](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/362)), and
  reported that the XER import decoded files as Latin-1 and so garbled Arabic and other
  non-Western activity names
  ([#460](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/460)).
- **Elric** ([@elric-cpu](https://github.com/elric-cpu)): sent a pull request proposing a
  guarded job workflow that turns an accepted estimate into a job with planning and delivery
  states ([#364](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/364)).
- **Arthur Ganem** ([@LetsBIMtogether](https://github.com/LetsBIMtogether)): sent a pull
  request proposing a spacing fix for the ASCII diagrams in the README
  ([#370](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/370)).
- **baguscandrautamamr** ([@baguscandrautamamr](https://github.com/baguscandrautamamr)): sent
  a pull request proposing an importer for model and sheet dumps pulled from a BIM authoring
  tool over MCP
  ([#415](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/415)).
- **ziul03** ([@ziul03](https://github.com/ziul03)): reported that raw tool-calling tags
  rendered as plain text in chat with third-party providers
  ([#417](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/417)), that
  deleted accounts stayed visible in user management with anonymised email addresses
  ([#418](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/418)), and
  that the AI provider was configured without tool access
  ([#424](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/424)).
- **Sontung05** ([@Sontung05](https://github.com/Sontung05)): reported that the Linux desktop
  app could not start its local database because a PostgreSQL dictionary library was missing
  ([#419](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/419)).
- **OleksandrDemydenko** ([@OleksandrDemydenko](https://github.com/OleksandrDemydenko)): asked
  in Discussions why draft contracts could not be deleted
  ([#425](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/425)),
  asked for a Ukrainian localisation with the hryvnia and a translated interface, which the
  app now ships
  ([#429](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/429)),
  and sent questions and comments on the 4D schedule and its tasks
  ([#456](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/456)).
- **juanjosecasba** ([@juanjosecasba](https://github.com/juanjosecasba)): reported through the
  in-app reporter that an in-app upgrade timed out from the resource catalog page
  ([#430](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/430)).
- **JimZed** ([@JimZed](https://github.com/JimZed)): reported through the in-app reporter that
  indexing the cost database for vector search timed out
  ([#436](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/436)).
- **CADcoLabs** ([@CADcoLabs](https://github.com/CADcoLabs)): sent a pull request proposing
  partner branding on the login page
  ([#437](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/437)).
- **Bluster83** ([@Bluster83](https://github.com/Bluster83)): asked in Discussions what a main
  contractor needs from a construction ERP, from an imported BOQ through procurement,
  valuations and cost control
  ([#440](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/440)).
- **mherrerap87** ([@mherrerap87](https://github.com/mherrerap87)): twelve reports across BI
  dashboards, custom KPIs, assemblies and migrations, including money KPIs that summed across
  currencies
  ([#465](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/465)), actual
  cost and hours that could not be attributed to a BOQ position
  ([#454](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/454)) and a
  migration upgrade that always failed because startup had already created its tables
  ([#449](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/449)), and
  nine more.
- **Dzintars** ([@dzintars](https://github.com/dzintars)): wrote in Discussions about the
  project continuity risk a company adopter sees when a platform depends on one maintainer
  ([#450](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions/450)).
- **stubbzy3-creator** ([@stubbzy3-creator](https://github.com/stubbzy3-creator)): sent a pull
  request proposing cross-department work requests, correspondence registers and a daily
  delivery board
  ([#464](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/464)).
- **Mazen S. H. Elsayed** ([@elsayed-mazen](https://github.com/elsayed-mazen)): reported that
  the invoice total went blank for amounts of 1,000 or more
  ([#466](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/466)) and that
  approving a pending invoice set its status to Sent and blocked marking it paid
  ([#467](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/467)).
- **JoseJFernandezAlvarez**
  ([@JoseJFernandezAlvarez](https://github.com/JoseJFernandezAlvarez)): sent an in-app report
  from the Modules page
  ([#468](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/468)).

See the full list of everyone who has contributed:

https://github.com/datadrivenconstruction/OpenConstructionERP/graphs/contributors

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
