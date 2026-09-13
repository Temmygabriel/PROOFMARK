# Release Notes

## Changes

- Evidence is now a commit-pinned GitHub URL plus the sha256 of its exact bytes,
  replacing the content-addressed CID gateway entirely.
- Accepting a job now posts a bond at least equal to the coverage, so an upheld
  breach is paid out of the forfeited bond and never out of LP capital.
- Open policies are capped at ten per buyer and ten per agent.

## Compatibility

This release is backward compatible with every existing policy and requires no
storage migration.

Released version: 2.4.0
