# Compatibility Imports

This package contains temporary import bridges for the former flat service layout.
New code must import from `app.rag`, `app.sql`, `app.caching`, `app.ingestion`, or
`app.observability`. The bridges protect existing clients during the migration and
can be removed in a future major version after downstream imports are audited.
