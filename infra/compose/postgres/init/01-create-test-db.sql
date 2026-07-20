SELECT 'CREATE DATABASE autoclaw_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'autoclaw_test'
)\gexec
