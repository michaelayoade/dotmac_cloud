"""Fail-closed owner for the Cloud V1 product composition declaration.

This module does not pretend that source availability is adoption. A component
is production-ready only when the checked-in manifest carries immutable release
evidence and the application has activated that exact release.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import cast

_SHA = re.compile(r"[0-9a-f]{40}")


class Availability(StrEnum):
    """Repository-local view of whether an installable release exists."""

    RELEASED = "released"
    SOURCE_UNRELEASED = "source-unreleased"
    SOURCE_MISSING = "source-missing"


class Activation(StrEnum):
    """Whether this application actually composes the exact release."""

    PENDING = "pending"
    COMPOSED = "composed"


class Persistence(StrEnum):
    """Cloud's required persistence intent for one component."""

    FOUNDATION = "foundation"
    STATELESS = "stateless"
    TENANT = "tenant"


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    """Immutable release coordinates accepted by this assembly."""

    version: str
    tag: str
    peeled_commit: str


@dataclass(frozen=True, slots=True)
class CloudComponent:
    """One required Cloud V1 owner or foundation."""

    distribution: str
    import_package: str
    persistence: Persistence
    availability: Availability
    activation: Activation
    release: ReleaseEvidence | None
    blocker: str | None


@dataclass(frozen=True, slots=True)
class CompositionBlocker:
    """One reason production composition must remain closed."""

    distribution: str
    code: str


@dataclass(frozen=True, slots=True)
class CompositionReport:
    """Deterministic production-readiness verdict."""

    components: tuple[CloudComponent, ...]
    blockers: tuple[CompositionBlocker, ...]

    @property
    def ready(self) -> bool:
        """Return true only when no component remains blocked."""
        return not self.blockers


class ManifestError(ValueError):
    """The checked-in composition declaration is malformed."""


class CompositionBlocked(RuntimeError):
    """Production composition is incomplete."""

    def __init__(self, blockers: tuple[CompositionBlocker, ...]) -> None:
        self.blockers = blockers
        detail = ", ".join(f"{item.distribution}:{item.code}" for item in blockers)
        super().__init__(f"Cloud V1 composition is not production-ready: {detail}")


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ManifestError(f"{context} must be an object with string keys")
    return cast(dict[str, object], value)


def _string(mapping: dict[str, object], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context}.{key} must be a non-empty string")
    return value


def _optional_string(mapping: dict[str, object], key: str, context: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context}.{key} must be null or a non-empty string")
    return value


def _release(
    raw: object,
    *,
    distribution: str,
    availability: Availability,
    context: str,
) -> ReleaseEvidence | None:
    if availability is not Availability.RELEASED:
        if raw is not None:
            raise ManifestError(f"{context}.release must be null until released")
        return None

    release = _mapping(raw, f"{context}.release")
    version = _string(release, "version", f"{context}.release")
    tag = _string(release, "tag", f"{context}.release")
    peeled_commit = _string(release, "peeled_commit", f"{context}.release")
    if tag != f"{distribution}-v{version}":
        raise ManifestError(f"{context}.release.tag must be {distribution}-v{version}")
    if _SHA.fullmatch(peeled_commit) is None:
        raise ManifestError(
            f"{context}.release.peeled_commit must be a 40-character git SHA"
        )
    return ReleaseEvidence(
        version=version,
        tag=tag,
        peeled_commit=peeled_commit,
    )


def _component(raw: object, index: int) -> CloudComponent:
    context = f"components[{index}]"
    item = _mapping(raw, context)
    distribution = _string(item, "distribution", context)
    import_package = _string(item, "import_package", context)
    try:
        persistence = Persistence(_string(item, "persistence", context))
        availability = Availability(_string(item, "availability", context))
        activation = Activation(_string(item, "activation", context))
    except ValueError as exc:
        raise ManifestError(f"{context} contains an unknown state") from exc

    release = _release(
        item.get("release"),
        distribution=distribution,
        availability=availability,
        context=context,
    )
    blocker = _optional_string(item, "blocker", context)
    if availability is Availability.RELEASED and blocker is not None:
        raise ManifestError(f"{context}.blocker must be null after release")
    if availability is not Availability.RELEASED and blocker is None:
        raise ManifestError(f"{context}.blocker is required until release")
    if activation is Activation.COMPOSED and release is None:
        raise ManifestError(f"{context} cannot be composed without a release")

    return CloudComponent(
        distribution=distribution,
        import_package=import_package,
        persistence=persistence,
        availability=availability,
        activation=activation,
        release=release,
        blocker=blocker,
    )


def _default_manifest_text() -> str:
    resource = files("dotmac_cloud").joinpath("cloud_v1_bom.json")
    return resource.read_text(encoding="utf-8")


def load_manifest(path: Path | None = None) -> tuple[CloudComponent, ...]:
    """Load and structurally validate one composition declaration."""
    text = (
        path.read_text(encoding="utf-8")
        if path is not None
        else _default_manifest_text()
    )
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"composition manifest is not valid JSON: {exc}") from exc

    root = _mapping(raw, "manifest")
    if root.get("schema_version") != 1:
        raise ManifestError("manifest.schema_version must equal 1")
    raw_components = root.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ManifestError("manifest.components must be a non-empty list")

    components = tuple(
        _component(item, index) for index, item in enumerate(raw_components)
    )
    names = tuple(item.distribution for item in components)
    if len(names) != len(set(names)):
        raise ManifestError("manifest.components contains a duplicate distribution")
    if names != tuple(sorted(names)):
        raise ManifestError("manifest.components must be sorted by distribution")
    return components


def evaluate(
    components: tuple[CloudComponent, ...] | None = None,
) -> CompositionReport:
    """Evaluate release availability and real application activation."""
    selected = components if components is not None else load_manifest()
    blockers: list[CompositionBlocker] = []
    for component in selected:
        if component.availability is not Availability.RELEASED:
            if component.blocker is None:
                raise ManifestError(
                    f"{component.distribution} has no release and no blocker"
                )
            blockers.append(
                CompositionBlocker(
                    distribution=component.distribution,
                    code=component.blocker,
                )
            )
        elif component.activation is not Activation.COMPOSED:
            blockers.append(
                CompositionBlocker(
                    distribution=component.distribution,
                    code="released_not_composed",
                )
            )
    return CompositionReport(components=selected, blockers=tuple(blockers))


def require_production_ready(
    report: CompositionReport | None = None,
) -> CompositionReport:
    """Return the report or refuse an incomplete production composition."""
    verdict = report if report is not None else evaluate()
    if not verdict.ready:
        raise CompositionBlocked(verdict.blockers)
    return verdict
