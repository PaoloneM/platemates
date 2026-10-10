# PostgreSQL with pgvector, plus pgBackRest for the public server's backups (continuous WAL
# archiving, full and differential backups: docs/operations.md). Only docker-compose.prod.yml
# uses this image; locally the plain pgvector image is enough.
FROM pgvector/pgvector:pg17

RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest /var/spool/pgbackrest

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
