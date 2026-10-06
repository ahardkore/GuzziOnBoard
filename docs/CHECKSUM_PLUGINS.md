# Calibration checksum plugins

GuzziOnBoard bundles no calibration checksum algorithm. Protocol-frame and
upload checksums elsewhere in the project are not interchangeable with checksum
fields inside a calibration image.

Put trusted Python plugins in `~/.guzzionboard/checksums/`. A plugin defines:

```python
PROVIDER_ID = "owner.algorithm-v1"
NAME = "Documented ECU checksum"
VERSION = "1.0.0"
SUPPORTED_CHECKSUMS = ("Exact XDFCHECKSUM title",)
VERIFIED = False
NOTE = "Algorithm source, test vectors, ECU/software and physical test status"

def update(image: bytes, context: dict) -> bytes:
    # Return same-length bytes. Do not mutate unrelated calibration data.
    ...

def verify(image: bytes, context: dict) -> bool:
    ...
```

## Isolation

The application never imports a local plugin into the server process. Metadata
inspection and every calculation run in a fresh `python -I -S -B` subprocess
with a clean temporary working directory and environment. The worker applies:

- a four-second parent timeout and two-second CPU limit;
- a 256 MiB address-space limit, 1 MiB file-size limit, and low descriptor and
  child-process limits where the operating system supports them;
- an audit hook denying network sockets, subprocess/process creation,
  environment mutation, filesystem writes, and reads outside the plugin file
  and standard-library tree;
- redirected plugin stdout/stderr and a size-limited JSON/base64 protocol;
- two calculations in separate fresh workers, which must produce identical
  bytes, followed by provider verification;
- a plugin-file SHA-256 recheck immediately before execution.

This is strong process/resource containment against mistakes and ordinary
malicious behavior. It is **not** described as a perfect kernel-grade sandbox:
the plugin is still native Python code executed as the workstation user. Only
install code you are willing to trust. A future deployment requiring hostile
multi-tenant plugins should use an OS container/VM with a read-only filesystem
and disabled network namespace.

## Selection and provenance

Providers are never auto-selected. The chosen id must explicitly support every
checksum title declared by the XDF. Preview and build preserve image length,
refuse more than 4096 changed bytes, and record provider id/version/source,
plugin SHA-256, isolation mode, input/output hashes, verification claim, and
every changed byte range. This makes behavior reviewable; it does not prove the
algorithm correct on a physical ECU.
