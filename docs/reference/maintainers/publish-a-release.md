# Publish a release

Release publication is blocked during WP-09. Its backend-only wheel and source distribution are contraction evidence, not release candidates. WP-10 must supply the independently authored root Console, browser proof, and one integrated build before this procedure becomes active.

Once that surface exists:

1. Set the intended version and finish the [release checklist](testing-and-release-checklist.md).
2. Run the then-current integrated release build.
3. Inspect both artifacts and run the installed-distribution verifier outside the checkout.
4. Publish those immutable artifacts through the project's package-index release process.
5. Install the published version in a clean environment and repeat the short smoke.
6. Record the exact checks and any intentionally skipped lanes.

Never replace an artifact for an existing version. Publish a new version for a correction.
