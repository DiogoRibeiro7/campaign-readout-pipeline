# Security

## Reporting a vulnerability

Please do not open a public issue. Report it privately through the
repository's [security advisories](https://github.com/DiogoRibeiro7/campaign-readout-pipeline/security/advisories/new),
or by email to dfr@esmad.ipp.pt.

## Supported versions

Only the latest release receives fixes.

## Scope

`readout fetch` downloads the source files from one pinned commit and refuses
any file whose SHA-256 differs from the one the contract names. A way to make
the pipeline read a file the contract does not name, or publish a result that
its gates refused, is in scope.
