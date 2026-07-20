# Publish a release

1. Set the intended version and finish the [release checklist](testing-and-release-checklist.md).
2. Run `make package-build` to create one wheel and one source distribution.
3. Inspect both artifacts and run the installed-distribution verifier outside the checkout.
4. Publish those immutable artifacts through the project's package-index release process.
5. Install the published version in a clean environment and repeat the short smoke.
6. Record the exact checks and any intentionally skipped lanes.

Never replace an artifact for an existing version. Publish a new version for a correction.
