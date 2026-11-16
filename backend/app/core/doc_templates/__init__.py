# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Documents and templates: the neutral core of editable document wording.

* :mod:`.registry` - document kinds modules register (the hook for any module);
* :mod:`.merge` - ``{{field}}`` substitution, nothing else;
* :mod:`.markup` - the small text format, escaped before it is converted;
* :mod:`.rules` - checks a text passes before it is published;
* :mod:`.resolve` - which wording a document prints;
* :mod:`.seller` - who the document is from (one resolver, swappable);
* :mod:`.legal` - locked legal blocks contributed by country packs.

Nothing here imports the database layer; the ``doc_templates`` module stores
the firm's texts and versions.
"""
