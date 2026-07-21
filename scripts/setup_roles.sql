-- Idempotent demo setup for Aurum's shared-database medallion topology.

CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS silver_candidates;
CREATE SCHEMA IF NOT EXISTS gold_candidates;

-- Create Roles if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'aurum_ingestion') THEN
        CREATE ROLE aurum_ingestion WITH LOGIN PASSWORD 'aurum_ingestion';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'aurum_generated_sql') THEN
        CREATE ROLE aurum_generated_sql WITH LOGIN PASSWORD 'aurum_generated_sql' NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'aurum_promotion') THEN
        CREATE ROLE aurum_promotion WITH LOGIN PASSWORD 'aurum_promotion';
    END IF;
END
$$;

ALTER ROLE aurum_generated_sql NOINHERIT;

GRANT USAGE ON SCHEMA source TO aurum_ingestion;
GRANT USAGE, CREATE ON SCHEMA bronze TO aurum_ingestion;
GRANT SELECT ON ALL TABLES IN SCHEMA source TO aurum_ingestion;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bronze TO aurum_ingestion;
ALTER DEFAULT PRIVILEGES IN SCHEMA source GRANT SELECT ON TABLES TO aurum_ingestion;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aurum_ingestion;
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO aurum_ingestion', current_database());
END
$$;

GRANT USAGE ON SCHEMA bronze TO aurum_generated_sql;
REVOKE CREATE ON SCHEMA silver FROM aurum_generated_sql;
REVOKE CREATE ON SCHEMA gold FROM aurum_generated_sql;
GRANT USAGE ON SCHEMA silver TO aurum_generated_sql;
GRANT USAGE ON SCHEMA gold TO aurum_generated_sql;
GRANT USAGE, CREATE ON SCHEMA silver_candidates TO aurum_generated_sql;
GRANT USAGE, CREATE ON SCHEMA gold_candidates TO aurum_generated_sql;
GRANT SELECT ON ALL TABLES IN SCHEMA bronze TO aurum_generated_sql;
GRANT SELECT ON ALL TABLES IN SCHEMA silver TO aurum_generated_sql;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT SELECT ON TABLES TO aurum_generated_sql;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT SELECT ON TABLES TO aurum_generated_sql;
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO aurum_generated_sql', current_database());
END
$$;

GRANT USAGE, CREATE ON SCHEMA silver TO aurum_promotion;
GRANT USAGE, CREATE ON SCHEMA gold TO aurum_promotion;
REVOKE aurum_generated_sql FROM aurum_promotion;
GRANT aurum_promotion TO aurum_generated_sql WITH INHERIT FALSE;
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO aurum_promotion', current_database());
END
$$;
