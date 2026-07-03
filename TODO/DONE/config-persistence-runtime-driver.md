# Config Persistence Runtime Driver

Purpose: close the dashboard save failure where production reported `Config persistence is unavailable, so settings were not saved.` because SQLAlchemy selected `psycopg2` from a bare `postgresql://` DSN while the backend image packages `psycopg`.

Status: done.

- [x] Normalize bare Postgres URLs to `postgresql+psycopg://` in the backend session factory.
- [x] Update CloudFormation so deployed backend tasks emit an explicit `postgresql+psycopg://` `DATABASE_URL`.
- [x] Add regression coverage for bare DSN normalization and the deployed CloudFormation DSN.
- [x] Update requirements, test spec, LLD, HLD, plan, and task acceptance criteria.
