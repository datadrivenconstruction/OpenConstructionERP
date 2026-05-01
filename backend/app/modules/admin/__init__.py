"""Admin module — operator endpoints for QA pipelines.

The qa-reset endpoint is the only public entrypoint here. It is intentionally
guarded by three independent gates so it cannot be hit by accident:

1. ``QA_RESET_ALLOWED=1`` env var must be set on the running process.
2. ``confirm_token`` body field must match ``os.environ["QA_RESET_TOKEN"]``
   (compared in constant time to defeat timing-oracle attacks).
3. The request hostname must look like a dev/staging environment
   (``localhost``, ``127.0.0.1``, ``staging``, ``test``, ``qa`` substrings).

Even with all three gates open, the destructive scope is whitelisted: only
projects/BOQs/etc. owned by the demo accounts (``demo@``, ``estimator@``,
``manager@openestimator.io``) are removed before reseeding.
"""
