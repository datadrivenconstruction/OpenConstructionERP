"""Cost-match module — CWICR automatic item matching (T12).

Three-tier matcher: exact → semantic → needs-review. Semantic stage
requires ``[semantic]`` extra (Qdrant + sentence-transformers). Without
it the module degrades gracefully — skips semantic stage, returns the
top-N same-category candidates as needs-review suggestions.
"""
