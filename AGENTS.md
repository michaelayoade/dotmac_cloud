# Agent rules — dotmac_cloud

This repository is the independent Dotmac Cloud product assembly. The accepted
business composition decision is Dotmac Starter ADR-0030 at the immutable
coordinate recorded in src/dotmac_cloud/cloud_v1_bom.json.

## Hard rules

1. Branch before committing. Commit, push, open, or merge a pull request only
   when Michael asks. Merge only after required CI is green.
2. Cloud owns its runtime, database, migrations, sessions, authorization, local
   links, adapter receipts, and product composition. It never reads another
   application's database, models, filesystem, or session.
3. Reusable modules are exact released dependencies. A source checkout, local
   path, branch, or version declaration is not production adoption evidence.
4. Business modules are peers. They never import one another. Cloud adapters
   translate only published typed outputs into published typed inputs and record
   deduplicated receipts.
5. Provider identity, endpoints, credentials, webhook verification, retry,
   checkpoints, and wire payloads belong to independently deployed Integrator
   connector plugins. No provider name or provider-specific field belongs under
   src/ or in the Cloud composition manifest.
6. Every stateful module has one explicit tenant-plane selection. No Cloud V1
   module may silently select a platform plane.
7. src/dotmac_cloud/composition.py is the sole owner of the production
   composition-readiness verdict. Adapters and commands report or enforce it;
   they do not reproduce the decision.
8. An unavailable owner keeps production readiness closed. Never weaken the
   gate, invent a release coordinate, or mark a component composed to make CI
   green.
9. Secrets are held, never dereferenced through settings. Store no credential
   value in Git, logs, tests, reports, prompts, or durable knowledge. Record only
   an approved secret-store reference.
10. Environment-specific values are settings with documented variables. No
    production host, domain, port, credential, or provider choice is hardcoded.
11. Poetry is an exact build input. pyproject.toml owns the version; CI,
    bootstrap requirements, and the lock must agree. Validation never repairs
    the lock.
12. Checked-in contracts and docs are sources of truth. Update
    docs/ARCHITECTURE.md and an ADR with any ownership or composition change.

## Validation

GitHub CI is the acceptance owner for the current Cloud track. Do not install
test or development dependencies or run tests on the local workstation.
Local work is limited to editing, formatting, and static checks that do not
install dependencies or execute tests.

The canonical CI command is make check. The deliberately stronger
make production-readiness remains red until every required owner is released
and really composed.
