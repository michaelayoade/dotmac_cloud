from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

from dotmac_cloud.composition import Activation, Persistence, load_manifest
from dotmac_cloud.module_planes import MODULE_PLANE_SELECTIONS

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "dotmac_cloud"
PROFILE = REPO / ".dotmac" / "standards-profile.json"
STANDARDS_WORKFLOW = REPO / ".github" / "workflows" / "engineering-standards.yml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

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


def _reservation_findings(text: str) -> tuple[str, ...]:
    """Return names that would mean Cloud reserves an effect before running it.

    At-most-once execution has one owner fleet-wide, `dotmac_kernel.idempotency`
    (Starter hard rule 21): nothing is reserved before the effect, and the
    fingerprint is its own column. An assembly that could claim, lease or
    reserve would be a second engine deciding the same question, which is the
    parallel authority this composition exists to prevent.

    Detection is over DEFINED names, not free text, so a docstring explaining
    the rule does not trip it — the premise is "Cloud defines no such
    operation", which is enforceable, rather than "Cloud never says the word",
    which is not.
    """
    tree = ast.parse(text)
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            defined.add(node.name)
    return tuple(
        sorted(
            name
            for name in defined
            if re.search(r"(?:^|_)(claim|lease|reserve|acquire)", name.lower())
        )
    )


def test_cloud_declares_no_second_idempotency_engine() -> None:
    findings: dict[str, tuple[str, ...]] = {}
    for path in sorted(SRC.rglob("*.py")):
        matches = _reservation_findings(path.read_text(encoding="utf-8"))
        if matches:
            findings[str(path.relative_to(REPO))] = matches

    assert findings == {}


def test_the_reservation_detector_has_a_sensitivity_proof() -> None:
    planted = "def claim_next_effect():\n    return None\n"

    assert _reservation_findings(planted) == ("claim_next_effect",)

    # And it must not fire on prose merely naming the rule, or the guard would
    # forbid documenting the boundary it enforces.
    assert _reservation_findings('"""Never claim or lease an effect."""\n') == ()


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
    # RECURSIVE. A non-recursive glob stopped at the top level, so an adapter in
    # `src/dotmac_cloud/adapters/` could import an owner this application never
    # composed and no guard would see it — the exact blindness this test exists
    # to prevent, one directory deeper.
    for path in sorted(SRC.rglob("*.py")):
        imported.update(_external_dotmac_imports(path))

    assert imported == activated_imports


def test_ci_round_trip_unwinds_every_composed_lineage_before_kernel() -> None:
    """A newly composed lineage cannot be left out of the downgrade proof."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    commands = re.findall(
        r"poetry run alembic downgrade ([a-z_]+)@base", workflow
    )

    # Module plane keys are the immutable branch labels used by these exact
    # released lineages. The foundation must be last because every other
    # branch declares a logical prerequisite supplied by it.
    assert commands == [
        "cloud_assembly",
        *(sorted(selection.module for selection in MODULE_PLANE_SELECTIONS)),
        "kernel",
    ]


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
