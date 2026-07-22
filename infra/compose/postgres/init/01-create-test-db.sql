SELECT 'CREATE DATABASE banksia_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'banksia_test'
)\gexec
