SELECT 'CREATE DATABASE oms_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'oms_test'
)\gexec
