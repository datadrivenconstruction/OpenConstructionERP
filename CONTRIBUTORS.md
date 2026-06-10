# Contributors

OpenConstructionERP is authored and owned by DataDrivenConstruction (see
[AUTHORS.md](AUTHORS.md)). The people listed here are contributors: they have sent
patches, fixes and feedback that made the project better. They are not authors of the
project, and authorship and copyright remain with DataDrivenConstruction.

Thank you to everyone who has contributed.

- **skolodi** ([@skolodi](https://github.com/skolodi)): issue reports and field feedback
  on the BOQ AI assistant.
- **Mourtadha Diop** ([@Mourdi59](https://github.com/Mourdi59)): fixed three BIM viewer
  bugs ([#159](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/159)),
  COLLADA namespace-prefix serialisation in `ifc_processor`, defence-in-depth regex
  tolerance in `ElementManager`, and `degraded` model status surfacing in the viewer UI.
- **rjohny** ([@rjohny55](https://github.com/rjohny55)): multi-area patch set
  ([#161](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/161)),
  defensive guards for the slow-query SQLAlchemy listener and the module-presence probe
  under concurrency, a FieldReport activity-rollup column fix, Qdrant multipart snapshot
  upload so app-container snapshots reach a separate Qdrant container, and three new AI
  providers, Kimi (Moonshot AI), Ollama and vLLM, with custom base URL support for the
  two local backends.
- **Jehad Baniowda** ([@jehadbaniodeh](https://github.com/jehadbaniodeh)): fixed the
  production Docker deployment and the takeoff viewer. The backend image now installs its
  dependencies and starts correctly
  ([#173](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/173)), nginx
  upgrades WebSocket connections so real-time notifications and presence work
  ([#176](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/176)), `.mjs`
  workers are served with the correct MIME type so the PDF takeoff viewer renders
  ([#175](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/175)), the
  upload ceiling is raised to 100M for PDF and CAD drawings
  ([#174](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/174)), and
  takeoff documents open in the in-app viewer instead of a broken download navigation
  ([#172](https://github.com/datadrivenconstruction/OpenConstructionERP/pull/172)).
- **Jérémy Christillin** ([@bvisible](https://github.com/bvisible)): feedback and feature
  proposals for the PDF takeoff module, in-canvas measurement editing and LLM-assisted
  plan reading
  ([#194](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/194)).
- **mohandshamada** ([@mohandshamada](https://github.com/mohandshamada)): issue reports on the
  converters version-check payload shape ([#195](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/195))
  and IFC zero-elements processing ([#197](https://github.com/datadrivenconstruction/OpenConstructionERP/issues/197)).

See the full list of everyone who has contributed:

https://github.com/datadrivenconstruction/OpenConstructionERP/graphs/contributors

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
