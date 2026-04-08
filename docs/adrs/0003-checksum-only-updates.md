# ADR-0003: Checksum-Only Updates

**Status:** Accepted
**Date:** 2026-01-15
**Decision makers:** Rohan R

---

## Context

envguard includes a self-update mechanism that downloads updates from a remote server. When an update is downloaded, its integrity must be verified before installation. The verification strategy is a critical security decision.

### Options for update verification

1. **No verification** — Download and install without any integrity check. Fast but insecure.
2. **Checksum-only (SHA-256)** — Compare the downloaded file's hash against a known-good hash from the manifest. Simple but does not guarantee authenticity.
3. **Checksum + GPG signature** — Verify the hash and a GPG signature from the release key. Stronger authenticity guarantee but requires key management.
4. **Checksum + Apple code signing** — Verify the hash and the code signature of the downloaded binary. Tied to Apple's infrastructure.
5. **Reproducible builds** — Users can rebuild the exact binary from source and compare hashes. Strongest guarantee but requires significant infrastructure.

---

## Decision

We will use **checksum-only verification with SHA-256** (option 2) for the initial version. The `SignatureVerifier` class in `security/signatures.py` implements chunked SHA-256 file hashing and comparison.

### Implementation

1. The remote manifest at `https://releases.envguard.dev/manifest.json` contains a `checksum` field (SHA-256 hex digest) and a `checksum_algorithm` field.
2. When an update is downloaded, `UpdateVerifier.verify_integrity()` computes the SHA-256 hash of the downloaded file and compares it against the manifest's checksum.
3. If the hashes don't match, a `VerificationError` is raised and the update is aborted.
4. The `signature` field in the manifest is reserved for future code signing but is not used in v0.1.0.

### Rationale

1. **Simplicity** — SHA-256 verification requires no key management, no certificate infrastructure, and no external dependencies beyond Python's standard library `hashlib`.

2. **Sufficient for initial release** — envguard is in alpha (v0.1.0). The threat model for an alpha release does not warrant the complexity of GPG signing or Apple code signing.

3. **Detects corruption** — Even without authenticity guarantees, checksum verification catches download corruption, network transmission errors, and CDN caching issues.

4. **Upgrade path** — The manifest already includes a `signature` field. Adding GPG or code signing verification in a future version requires only adding a verification step, not restructuring the manifest format.

### Why not stronger verification?

- **GPG signing** requires distributing a public key, managing key rotation, and integrating `gpg` or `python-gnupg` as a dependency. For an alpha release, this overhead is not justified.
- **Apple code signing** requires an Apple Developer account and is only applicable on macOS. It also requires `codesign` tooling and certificate management.
- **Reproducible builds** require a sophisticated CI pipeline, pinned build environments, and a way for users to verify builds independently. This is a significant engineering investment.

---

## Consequences

### Positive

- Simple implementation with no external dependencies.
- Catches download corruption and accidental modification.
- Manifest format is extensible for future signing.
- Fast verification (SHA-256 is hardware-accelerated on modern CPUs).

### Negative

- **No authenticity guarantee** — An attacker who compromises the release server can serve a correctly-checksummed malicious package. envguard cannot distinguish between a legitimate release and a forged one if the server is compromised.
- **No certificate pinning** — HTTPS connections use the system's default trust store. A compromised CA could enable MITM attacks on the update channel.
- **False sense of security** — Users may assume that "verified" means "authenticated" when it only means "not corrupted."

### Mitigations

- The update mechanism is **opt-in** — Users can set `channel = "off"` to disable automatic updates and manage updates manually via `pip install envguard==<version>`.
- Users can pin specific versions to avoid unexpected updates.
- The threat model document explicitly states that checksum-only verification does not guarantee authenticity.

---

## Future roadmap

When envguard reaches beta or stable, the following improvements should be considered:

1. **GPG signature verification** — Add GPG signature to manifest. Distribute public key via HTTPS from a separate domain. Verify signature before applying updates.

2. **TLS certificate pinning** — Pin the certificate of the release server to prevent MITM by compromised CAs.

3. **Reproducible builds** — Publish build instructions and toolchain hashes so users can verify that the published binary matches a from-source build.

4. **TUF (The Update Framework)** — Consider adopting TUF for a more robust update framework with role-based signing and gradual rollout.

---

## Related

- [docs/threat-model.md](../threat-model.md) — Update mechanism attack surface
- [docs/update-model.md](../update-model.md) — Full update model documentation
- [docs/security/README.md](../security/) — Security documentation
