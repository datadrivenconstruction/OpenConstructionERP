-- PostgreSQL init script for OpenEstimate
-- Run on first docker compose up

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- Fuzzy text search
-- CREATE EXTENSION IF NOT EXISTS "vector";   -- pgvector (uncomment if installed)
-- CREATE EXTENSION IF NOT EXISTS "duckdb";   -- pg_duckdb (uncomment if installed)
