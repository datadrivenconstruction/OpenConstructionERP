"""Currency / FX module.

Live foreign-exchange conversion for the platform's multi-currency cost bases
and estimates, plus optional purchasing-power-parity (PPP) conversion.

Market rates come from the European Central Bank daily reference feed (EUR
based), are cached in the database, and fall back to a small bundled seed of
major currencies when the network is unavailable, so conversion degrades
gracefully with no hard network dependency.
"""
