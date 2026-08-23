from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

from dotmac_cloud.composition import Activation, Persistence, load_manifest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "dotmac_cloud"
PROFILE = REPO / ".dotmac" / "standards-profile.json"
STANDARDS_WORKFLOW = REPO / ".github" / "workflows" / "engineering-standards.yml"

FORBIDDEN_PROVIDER_NAMES = (
    "cocca",
    "cpanel",
    "directadmin",
    "flutterwave",
    "nira",
    "openprovider",
    "paystack",
    "powerdns",
    "whmcs",
)

STATELESS = {
    "dotmac-auth-oidc",
    "dotmac-document-rendering",
    "dotmac-storefront",
    "dotmac-ui",
}


def _provider_findings(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(
        name
        for name in FORBIDDEN_PROVIDER_NAMES
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lowered)
    )


def _external_dotmac_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return {
        name
        for name in imports
        if name.startswith("dotmac_") and name != "dotmac_cloud"
    }


def test_provider_identity_does_not_enter_cloud_source_or_composition() -> None:
    findings: dict[str, tuple[str, ...]] = {}
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in {".py", ".json"}:
            continue
        matches = _provider_findings(path.read_text(encoding="utf-8"))
        if matches:
            findings[str(path.relative_to(REPO))] = matches

    assert findings == {}


def test_the_provider_detector_has_a_sensitivity_proof() -> None:
    planted = "if provider == 'paystack': call_provider()"

    assert _provider_findings(planted) == ("paystack",)


def test_integrator_and_v1_exclusions_are_not_composed() -> None:
    distributions = {item.distribution for item in load_manifest()}

    assert "dotmac-integration" not in distributions
    assert "dotmac-fx-policy" not in distributions
    assert "dotmac-service-orders" not in distributions


def test_every_stateful_cloud_component_selects_the_tenant_plane() -> None:
    components = load_manifest()

    assert {
        item.distribution
        for item in components
        if item.persistence is Persistence.STATELESS
    } == STATELESS
    assert (
        next(
            item for item in components if item.distribution == "dotmac-kernel"
        ).persistence
        is Persistence.FOUNDATION
    )
    assert all(
        item.persistence is Persistence.TENANT
        for item in components
        if item.distribution not in STATELESS | {"dotmac-kernel"}
    )


def test_only_activated_components_may_be_runtime_dependencies() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    raw_dependencies = project["project"]["dependencies"]
    assert isinstance(raw_dependencies, list)
    dotmac_dependencies: dict[str, str] = {}
    for raw in raw_dependencies:
        assert isinstance(raw, str)
        if not raw.startswith("dotmac-"):
            continue
        match = re.fullmatch(r"(dotmac-[a-z0-9-]+)==([0-9A-Za-z.]+)", raw)
        assert match is not None, f"Dotmac dependency is not exact: {raw}"
        dotmac_dependencies[match.group(1)] = match.group(2)
    components = load_manifest()
    activated = {
        item.distribution
        for item in components
        if item.activation is Activation.COMPOSED
    }

    assert set(dotmac_dependencies) == activated
    for component in components:
        if component.activation is not Activation.COMPOSED:
            continue
        assert component.release is not None
        assert dotmac_dependencies[component.distribution] == component.release.version


def test_source_imports_only_activated_dotmac_components() -> None:
    activated_imports = {
        item.import_package
        for item in load_manifest()
        if item.activation is Activation.COMPOSED
    }
    imported: set[str] = set()
    for path in sorted(SRC.glob("*.py")):
        imported.update(_external_dotmac_imports(path))

    assert imported == activated_imports


def test_governance_profile_and_workflow_pin_the_same_revision() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    workflow = STANDARDS_WORKFLOW.read_text(encoding="utf-8")
    revision = profile["governance_model"]["revision"]

    assert profile["schema_version"] == 9
    assert profile["enforcement_mode"] == "required"
    assert f"standards-check@{revision}" in workflow
    assert re.fullmatch(r"[0-9a-f]{40}", revision)


def test_every_remote_workflow_action_is_immutable() -> None:
    failures: list[str] = []
    for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("- uses:"):
                continue
            value = stripped.removeprefix("- uses:").strip().split()[0]
            if value.startswith("./"):
                continue
            revision = value.rsplit("@", maxsplit=1)[-1]
            if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
                failures.append(f"{path.name}:{line_number}:{value}")

    assert failures == []
