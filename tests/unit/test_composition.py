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
        "dotmac-billing",
        "dotmac-brand-profiles",
        "dotmac-collections",
        "dotmac-document-rendering",
        "dotmac-durable-timers",
        "dotmac-files",
        "dotmac-fulfillment",
        "dotmac-kernel",
        "dotmac-numbering",
        "dotmac-party",
        "dotmac-payments",
        "dotmac-subscriptions",
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


def test_four_commerce_releases_are_recorded_without_claiming_composition() -> None:
    expected = {
        "dotmac-billing": ReleaseEvidence(
            version="0.1.0a1",
            tag="dotmac-billing-v0.1.0a1",
            peeled_commit="92a1626b16d7e068f92536d8cfcb2ef9b6f270c2",
        ),
        "dotmac-collections": ReleaseEvidence(
            version="0.1.0a1",
            tag="dotmac-collections-v0.1.0a1",
            peeled_commit="6ecf518a6985b8bf4b163eccb3de2fef171ecccc",
        ),
        "dotmac-fulfillment": ReleaseEvidence(
            version="0.1.0a1",
            tag="dotmac-fulfillment-v0.1.0a1",
            peeled_commit="be02e28d11a0ba849b4974273f5a2d4bd7806a4a",
        ),
        "dotmac-subscriptions": ReleaseEvidence(
            version="0.1.0a1",
            tag="dotmac-subscriptions-v0.1.0a1",
            peeled_commit="ffe483fb53f12dd7aee400a39e0c85ecf308470f",
        ),
    }
    components = {component.distribution: component for component in load_manifest()}

    for distribution, release in expected.items():
        assert components[distribution].release == release
        assert components[distribution].activation is Activation.PENDING


def test_document_rendering_release_is_recorded_as_availability_only() -> None:
    """A stateless owner's release is evidence, never activation."""
    component = next(
        item
        for item in load_manifest()
        if item.distribution == "dotmac-document-rendering"
    )

    assert component.persistence is Persistence.STATELESS
    assert component.availability is Availability.RELEASED
    assert component.blocker is None
    assert component.release == ReleaseEvidence(
        version="0.1.0a1",
        tag="dotmac-document-rendering-v0.1.0a1",
        peeled_commit="6edaac845f3ced4270bd23edb72c4aa8cf8315e2",
    )
    assert component.activation is Activation.PENDING


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
