# ADR-0001: Dotmac Cloud is an independent fail-closed product assembly

Status: Accepted

Date: 2026-08-23

Amended: 2026-08-23 — repository visibility corrected from private to public.


## Context

Dotmac Starter ADR-0030 assigns Cloud a greenfield application composition of
reusable domain owners. Starter's reference assembly is not the Cloud product,
and the source tree currently contains owners in three different states:
released, complete but deliberately unreleased, and not yet on main.

Treating any of those states as equivalent would either turn Starter into the
product or claim an installable composition that does not exist.

## Decision

Cloud is an independent repository and application (public — see the
2026-08-23 amendment). The first slice
ships a typed, immutable, fail-closed composition gate and the frozen V1 bill
of materials. A component is ready only after both conditions hold:

1. the manifest records immutable release coordinates; and
2. this application has exact-pinned, migrated, wired, and proven that release.

Until then production readiness is false. External connector identity and
transport stay entirely in Integrator. Cloud V1 stateful modules select the
tenant plane explicitly.

The upstream decision coordinate is:

- repository: https://github.com/michaelayoade/dotmac_starter_mt
- commit: 64b26751e026aec34e427ac2123f2c38cb20540c
- path: docs/adr/0030-cloud-commerce-is-composed-from-complete-domain-owners.md

## Amendment 2026-08-23 — the repository is public

The Decision above was written saying "a private independent repository". That
was wrong at the time it was accepted, not merely overtaken: the approved
policy and the GitHub setting are both **public**
(`gh repo view michaelayoade/dotmac_cloud` reports `visibility=PUBLIC`,
`isPrivate=false`).

The word is struck. Nothing else in this decision changes, because nothing else
depended on it — "private" was never load-bearing for the fail-closed gate,
which is what this ADR actually decides.

It is corrected rather than quietly edited because visibility governs what may
be written down here. A public repository means, permanently and for every
later slice:

- **No secret value, ever** — not a key, token, password, connection string,
  PSP or registrar credential, EPP password, or domain-transfer auth code.
  Only an approved OpenBao path or a local pointer. This already follows from
  Integrator holding provider identity and credentials, and being public makes
  it unforgiving rather than merely correct.
- **No customer, registrant or tenant data** in fixtures, tests, dossiers,
  issues or commit messages — registrar contact PII included.
- **No host name, IP, internal topology or deployment coordinate** for a
  production target. Deployment evidence names an image digest and a run, not
  an address.
- Commit history is permanent and world-readable. A secret pushed here is
  compromised the moment it lands and must be rotated, not reverted.

## Consequences

The foundation can be reviewed and governed without publishing withheld
modules or pretending a path dependency is production adoption. Production
deployment remains impossible by construction. Later slices change one owner
from pending to composed only alongside its exact pin, plane selection,
adapter, reconciliation path, and CI evidence.
