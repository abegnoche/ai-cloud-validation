# Follow-up: requirement_ids backfill across all SEC* validations

Internal note. Captures pause state for the `@requirement_ids` rollout so
we can resume cleanly when the spec-ID source-of-truth script lands.

## Current state

- **Decorator infrastructure landed** in `isvtest/src/isvtest/core/validation.py`:
  `@requirement_ids("SEC02-01")` attaches a `requirement_ids: ClassVar[list[str]]`
  to a `BaseValidation` subclass. Default is `[]` for undecorated checks.
- **Surfaced** in `BaseValidation.execute()` return dict and in
  `catalog.build_catalog()` entries (new `requirement_ids` field).
- **Applied to one check only:** `ShortLivedCredentialsCheck` →
  `["SEC02-01"]` (`isvtest/src/isvtest/validations/security.py`).
- Tests live in `isvtest/tests/test_validation.py`
  (class `TestRequirementIdsDecorator` + a regression test pinning
  `ShortLivedCredentialsCheck` to `SEC02-01`) and
  `isvtest/tests/test_catalog.py`
  (`test_requirement_ids_surfaced_for_decorated_check`).

PR: `feat/requirement-ids-decorator` →
<https://github.com/abegnoche/ISV-NCP-Validation-Suite/pull/new/feat/requirement-ids-decorator>.

## What we're waiting on

John Kenyon (jkenyon-nvidia) is committing a script to this repo that
generates the validation → spec-ID mapping from the upstream NVIDIA
requirements document. Until that lands we don't have a stable,
reviewable source of truth for backfilling the rest of the SEC*
validations.

The current Google Sheet
(`https://docs.google.com/spreadsheets/d/1uuYJ1BenYADNKum_cRC3tRDlT0V5F0-IojvH5NInghA`)
is access-gated and prone to rot, so we deliberately did **not** wire
it directly into the codebase.

## Resume checklist (when the generator script lands)

1. Run the script against `main`. Confirm it produces a deterministic
   mapping of `validation_class_name → list[requirement_id]`.
2. Decide whether to (a) consume the mapping at runtime (script writes
   a JSON file, decorator/manifest reads it) or (b) run it once and
   commit the `@requirement_ids(...)` decorations into source. Prefer
   (b) for grep-ability and reviewability; (a) only if the mapping
   churns frequently enough to make commits noisy.
3. Backfill remaining SEC* validations in
   `isvtest/src/isvtest/validations/security.py`:
   - `BmcManagementNetworkCheck`, `BmcTenantIsolationCheck`,
     `BmcProtocolSecurityCheck` (CNP10-01), `BmcBastionAccessCheck` (SEC12-03)
   - `ApiEndpointIsolationCheck`
   - `MfaEnforcedCheck` (SEC07-01)
   - `CustomerManagedKeyCheck` (SEC09-04)
   - `ServiceAccountCredentialCheck`
   - `OidcUserAuthCheck` (SEC01-01)
   - Plus any non-SEC* validations the generator covers (NET*, CNP*, ...)
4. Add a CI check that fails if a validation listed in the manifest
   lacks `@requirement_ids(...)` (or vice versa).
5. Drop this file.

## Why we paused (so future-you doesn't redo the analysis)

Rolling out `@requirement_ids` to all 100+ validations by hand without
a generator means:

- Every reviewer has to cross-reference each ID by hand against the
  spec, which is slow and error-prone.
- IDs in the spec change occasionally; manual decorations drift.
- The generator gives us one obvious place to assert correctness
  (and a CI check, see step 4 above).

The cost of waiting is one more commit / PR after John's script lands;
the cost of *not* waiting is a hand-curated mapping that we'll have
to reconcile later anyway.
