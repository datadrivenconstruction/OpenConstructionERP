"""Compliance-AI module — DSL engine + NL rule builder.

Tasks in scope (see ``CLAUDE-DASHBOARDS.md``):
    T08 Compliance DSL Engine (extends core ValidationRule)
    T13 Natural Language Compliance Rule Builder

Design principle: the DSL compiler produces ``ValidationRule`` subclasses
registered with ``app.core.validation.rule_registry``, so every compliance
evaluation runs through the single validation engine (no parallel
pipeline). Fail entities are stored in a child table, not a JSONB blob.
"""
