# schema.sh <db> <outdir>: dump columns / indexes / constraints of the public schema, sorted.
set -eu
db=$1; out=$2; mkdir -p "$out"
q() { PGPASSWORD=oe psql -h localhost -U oe -d "$db" -Atc "$1" | LC_ALL=C sort; }
q "select table_name||'.'||column_name||' '||data_type||coalesce('('||character_maximum_length||')','')||coalesce('('||numeric_precision||','||numeric_scale||')','')||' null='||is_nullable||' def='||coalesce(column_default,'') from information_schema.columns where table_schema='public'" >"$out/columns.txt"
q "select tablename||' '||regexp_replace(indexdef, ' ON public\.\S+', ' ON _') from pg_indexes where schemaname='public'" >"$out/indexes.txt"
q "select conrelid::regclass||' '||contype||' '||pg_get_constraintdef(oid)||' valid='||convalidated from pg_constraint where connamespace='public'::regnamespace" >"$out/constraints.txt"
q "select table_name from information_schema.tables where table_schema='public'" >"$out/tables.txt"
wc -l "$out"/*.txt
