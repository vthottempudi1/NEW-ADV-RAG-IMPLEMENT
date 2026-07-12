# Database Assets

- `migrations/` contains ordered, idempotent schema/data migrations used by the seed tool.
- `seeds/` is reserved for explicit environment-safe seed manifests.

Production schema changes should eventually be managed by Alembic with a recorded
version table. The existing numbered SQL files are retained to avoid changing the
deployed database contract during this repository-only reorganization.
