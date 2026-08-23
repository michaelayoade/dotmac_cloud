# ADR-0001: Dotmac Cloud is an independent fail-closed product assembly

Status: Accepted

Date: 2026-08-23

## Context

Dotmac Starter ADR-0030 assigns Cloud a greenfield application composition of
reusable domain owners. Starter's reference assembly is not the Cloud product,
and the source tree currently contains owners in three different states:
released, complete but deliberately unreleased, and not yet on main.

Treating any of those states as equivalent would either turn Starter into the
product or claim an installable composition that does not exist.

## Decision

Cloud is a private independent repository and application. The first slice
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

## Consequences

The foundation can be reviewed and governed without publishing withheld
modules or pretending a path dependency is production adoption. Production
deployment remains impossible by construction. Later slices change one owner
from pending to composed only alongside its exact pin, plane selection,
adapter, reconciliation path, and CI evidence.
