# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence - smarts on top of the correspondence register.

Listens to ``correspondence.created`` and enriches each incoming record
with a classification, extracted facts (prices, quote numbers, dates,
commitments), link suggestions and a reply-needed flag. Heuristics run
on every message at zero cost; the configured AI provider (Settings >
AI) deepens the analysis on demand. Nothing mutates a correspondence
row until a person confirms the suggestion.
"""
