-- Stale compile lock (SPEC §12b): when the version entered `compiling`.
-- NULL whenever the version is not compiling.

ALTER TABLE policy_versions ADD COLUMN compiling_since TEXT;
