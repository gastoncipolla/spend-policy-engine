"""SQLite persistence: connection, migrations and one repository module per area.

Repositories are plain functions taking a `sqlite3.Connection`. They never open
transactions; services do (see `covered.store.db.transaction`).
"""
