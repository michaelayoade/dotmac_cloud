# Dotmac Cloud

Dotmac Cloud is an independent product application that composes reusable
Dotmac commerce and service owners. It is not a facade over Dotmac Sub, does not
share another application's database, and contains no provider client.

This repository is currently a foundation, not a production-ready service. The
checked-in Cloud V1 bill of materials records immutable evidence for owners that
are released and explicit blocker codes for owners that are not. Every
component also remains uncomposed here. The production gate therefore refuses
the build by design until real package pins, migration plane selections, typed
adapters, and reconciliation paths land.

The authoritative business decision is
dotmac_starter_mt/docs/adr/0030-cloud-commerce-is-composed-from-complete-domain-owners.md
at the exact Starter commit recorded in the manifest.

## Commands

- make check — canonical CI validation.
- make readiness-report — machine-readable current composition report.
- make production-readiness — fail unless every V1 owner is released and
  composed.

No credential belongs in this repository. The independently deployed Dotmac
Integrator owns external connector bindings, secret references, transport
evidence, retries, checkpoints, health, and repair.
