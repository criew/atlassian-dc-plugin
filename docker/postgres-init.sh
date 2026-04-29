#!/bin/bash
# Per-product Postgres roles + databases for the Atlassian stack.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE USER jira WITH PASSWORD 'jira';
    CREATE DATABASE jiradb WITH OWNER jira ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;

    CREATE USER confluence WITH PASSWORD 'confluence';
    CREATE DATABASE confluencedb WITH OWNER confluence ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;

    CREATE USER bitbucket WITH PASSWORD 'bitbucket';
    CREATE DATABASE bitbucketdb WITH OWNER bitbucket ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
EOSQL
