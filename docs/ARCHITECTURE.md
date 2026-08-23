# Dotmac Cloud architecture

## Application boundary

Dotmac Cloud is one independently deployed application with its own runtime,
database, migrations, sessions, authorization, local link rows, adapter receipt
ledger, and repair processes. Cross-application integration is only through
versioned APIs and webhooks. Cloud never reads Dotmac Sub, Vendor Control Plane,
ERP, CRM, or Integrator storage.

Reusable modules are installed locally as exact released artifacts. Stateful
Cloud modules select only their tenant plane. Provider transports are not
modules in this application: the separately deployed Integrator discovers and
runs connector plugins.

## Current construction state

The first foundation slice deliberately has no active Dotmac package
dependencies. src/dotmac_cloud/cloud_v1_bom.json is a fail-closed construction
ledger:

- released means an immutable tag and peeled commit are recorded;
- source-unreleased or source-missing names the actual blocker;
- pending means this application has not yet exact-pinned, migrated, wired, and
  proven the owner; and
- composed will be set only in the same reviewed change that adds the exact
  dependency, explicit plane, adapter, migration binding, and CI proof.

Source availability is not adoption, and this negative ledger is not a release
oracle. It records only the immutable release evidence already accepted by this
assembly and refuses every unsupported positive claim.

## Ownership map

| Fact or decision | Sole owner in this repository |
|---|---|
| Cloud V1 BOM parsing and production-readiness verdict | dotmac_cloud.composition |
| Product-local adapter receipts and reconciliation | Cloud assembly, not yet implemented |
| Offer, subscription, order, payment, tax, receivable, dunning, fulfillment, domain, and hosting decisions | Their exact-pinned reusable owner modules |
| External transport, provider binding, secret materialization, retry, checkpoints, and delivery evidence | Independently deployed Dotmac Integrator |

## Next composition slice

The next slice adds the first real typed adapter against reviewed module
contracts. It must keep modules as peers, record an idempotent receipt, add the
module's exact released dependency and tenant-plane selection, and prove replay
and missed-delivery repair. No component becomes composed merely because its
source or release exists.
