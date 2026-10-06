# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Readers for the Italian regional price lists (prezzari regionali).

One reader per publisher format, each producing :class:`~.base.PriceListRow`
rows and a :class:`~.base.PriceListSource`; :mod:`.service` recognises the
format of an upload, previews it and maps the rows to cost items.
"""
