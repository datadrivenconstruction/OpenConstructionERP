# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assistant proposals that a person reviews, applies, rejects or undoes.

Public API for the chat stream:

* :func:`app.modules.erp_chat.actions.service.propose_tool_result` - handle a
  ``propose_*`` tool call; returns the tool result dict (flushes, no commit).
* :func:`app.modules.erp_chat.actions.registry.tool_definitions` - the
  ``propose_*`` tools in Anthropic format; ``get_spec_for_tool`` routes a call.

Imports are kept lazy here so that importing the package (e.g. from the model
registry) never pulls in the BOQ or tasks modules.
"""
