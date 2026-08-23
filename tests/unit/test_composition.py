from __future__ import annotations

import json
from pathlib import Path

import pytest

from dotmac_cloud.composition import (
    Activation,
    Availability,
    CloudComponent,
    CompositionBlocked,
    ManifestError,
    Persistence,
    ReleaseEvidence,
    evaluate,
    load_manifest,
    require_production_ready,
)

EXPECTED_DISTRIBUTIONS = (
    "dotmac-auth-oidc",
    "dotmac-billing",
    "dotmac-brand-profiles",
    "dotmac-collections",
    "dotmac-document-rendering",
    "dotmac-domains",
    "dotmac-durable-timers",
    "dotmac-files",
    "dotmac-fulfillment",
    "dotmac-hosting",
    "dotmac-kernel",
    "dotmac-numbering",
    "dotmac-orders",
    "dotmac-party",
    "dotmac-payments",
    "dotmac-storefront",
    "dotmac-subscriptions",
    "dotmac-tax",
    "dotmac-ui",
)


def test_the_cloud_v1_bom_is_complete_and_sorted() -> None:
    components = load_manifest()

    assert tuple(item.distribution for item in components) == EXPECTED_DISTRIBUTIONS
    assert all(item.activation is Activation.PENDING for item in components)


def test_release_evidence_is_not_misreported_as_composition() -> None:
    report = evaluate()

    assert report.ready is False
    assert len(report.blockers) == len(EXPECTED_DISTRIBUTIONS)
    assert {
        blocker.distribution
        for blocker in report.blockers
        if blocker.code == "released_not_composed"
    } == {
        "dotmac-auth-oidc",
        "dotmac-brand-profiles",
        "dotmac-durable-timers",
        "dotmac-files",
        "dotmac-kernel",
        "dotmac-numbering",
        "dotmac-party",
        "dotmac-payments",
        "dotmac-tax",
        "dotmac-ui",
    }


def test_kernel_a94_has_immutable_release_coordinates() -> None:
    kernel = next(
        item for item in load_manifest() if item.distribution == "dotmac-kernel"
    )

    assert kernel.release == ReleaseEvidence(
        version="0.1.0a94",
        tag="dotmac-kernel-v0.1.0a94",
        peeled_commit="9e717eb88603f6ef61bded23b2aa468fe4533a95",
    )


def test_production_gate_refuses_the_foundation_state() -> None:
    with pytest.raises(CompositionBlocked) as raised:
        require_production_ready()

    assert raised.value.blockers


def test_the_gate_can_accept_a_genuinely_composed_release() -> None:
    component = CloudComponent(
        distribution="dotmac-example",
        import_package="dotmac_example",
        persistence=Persistence.STATELESS,
        availability=Availability.RELEASED,
        activation=Activation.COMPOSED,
        release=ReleaseEvidence(
            version="1.2.3",
            tag="dotmac-example-v1.2.3",
            peeled_commit="a" * 40,
        ),
        blocker=None,
    )

    report = require_production_ready(evaluate((component,)))

    assert report.ready is True
    assert report.blockers == ()


def test_a_release_tag_must_match_the_distribution_and_version(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema_version": 1,
        "components": [
            {
                "distribution": "dotmac-example",
                "import_package": "dotmac_example",
                "persistence": "stateless",
                "availability": "released",
                "activation": "pending",
                "release": {
                    "version": "1.2.3",
                    "tag": "wrong-v1.2.3",
                    "peeled_commit": "a" * 40,
                },
                "blocker": None,
            }
        ],
    }
    path = tmp_path / "bom.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="release.tag"):
        load_manifest(path)
