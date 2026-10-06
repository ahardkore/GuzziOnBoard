# Recommendation packages

GuzziOnBoard bundles **zero** recommendation packages and no generic tune
values. `~/.guzzionboard/recommendations/*.json` is a local registry for
third-party packages that operators may maintain or exchange independently.
Every loaded package is labelled `user-supplied-unendorsed`.

A `guzzionboard.recommendation/v1` package requires:

- lowercase id, semantic version, title and license;
- maintainer name plus inspectable HTTP(S) URL;
- ECU family, motorcycle, hardware and configuration-specific fitment;
- exact XDF filename and SHA-256;
- at least one evidence title/URL/applicability rationale;
- explicit table/constant/axis changes with stable id, target engineering value,
  and `expected_raw` source lock;
- real-ECU and dyno status, each one of `not-provided`, `reported`, or
  `independently-reproduced`; any positive claim needs evidence URLs.

The UI refuses staging unless the rendered XDF filename/hash, selected ECU
family, motorcycle and every raw source value match. It then asks the operator
to confirm the declared configuration and imports the package evidence into the
ordinary builder. Preview and build independently reload the package from disk,
verify its package SHA-256, require selected motorcycle and known hardware
identity, require the exact XDF filename/hash and evidence source, and require
the plan to contain exactly the package's raw locks and target values. Package
identity and claims are included in the reviewed plan hash and output manifest.
Any manual edit breaks the package lock until the package is restaged or
explicitly detached.

Preview, quantization, checksum, liability, and separate programming gates still
apply. Package structure and links can be validated; maintainer competence,
claims and tune safety cannot be inferred from valid JSON.
