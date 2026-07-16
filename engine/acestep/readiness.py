from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from engine.acestep.config import (
    OFFICIAL_CHECKPOINT_IDENTITY,
    OFFICIAL_PROVENANCE_URL,
    OFFICIAL_WEIGHT_DIGESTS,
    PINNED_UPSTREAM_COMMIT,
    PRIMARY_WEIGHT_PATH,
    REQUIRED_WEIGHT_PATHS,
    AceStepConfig,
)
from engine.models import LicenseId

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PINNED_CHECKPOINT_PATTERN = re.compile(r"^[^/@]+/[^/@]+@[0-9a-f]{40}/.+$")


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    issues: tuple[ReadinessIssue, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    @property
    def issue_codes(self) -> set[str]:
        return {issue.code for issue in self.issues}

    @property
    def summary(self) -> str:
        if self.ready:
            return "ACE-Step 1.5 is ready"
        return "; ".join(issue.message for issue in self.issues)


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as checkpoint:
        for chunk in iter(lambda: checkpoint.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upstream_checkout_commit(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    commit = result.stdout.strip().lower()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return None
    return commit


def upstream_checkout_is_clean(project_root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return not result.stdout.strip()


def inspect_readiness(
    config: AceStepConfig,
    *,
    dependency_probe: Callable[[], bool],
) -> ReadinessReport:
    issues: list[ReadinessIssue] = []
    _check_license(config, issues)
    _check_variant(config, issues)
    _check_identity(config, issues)
    _check_provenance(config, issues)
    _check_upstream_commit(config, issues)
    _check_weight_manifest(config, issues)
    if not dependency_probe():
        issues.append(
            ReadinessIssue(
                "optional_dependency_missing",
                "ACE-Step 1.5 is not installed; run uv sync in the pinned ACE-Step-1.5 "
                "checkout and expose its package to this environment",
            )
        )
    return ReadinessReport(tuple(issues))


def _check_license(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    if config.model_license is not LicenseId.MIT:
        issues.append(
            ReadinessIssue(
                "model_license_unverified",
                "official ACE-Step checkpoint activation requires its verified MIT license",
            )
        )


def _check_variant(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    if config.config_path != "acestep-v15-turbo":
        issues.append(
            ReadinessIssue(
                "model_variant_unverified",
                "Phase 1 supports only the verified acestep-v15-turbo checkpoint",
            )
        )


def _check_identity(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    if not config.checkpoint:
        issues.append(
            ReadinessIssue(
                "checkpoint_identity_missing",
                "configure a checkpoint identity containing its repository, immutable revision, "
                "and file",
            )
        )
    elif not _PINNED_CHECKPOINT_PATTERN.fullmatch(config.checkpoint):
        issues.append(
            ReadinessIssue(
                "checkpoint_identity_unpinned",
                "checkpoint identity must use owner/repository@40-character-revision/file syntax",
            )
        )
    elif config.checkpoint != OFFICIAL_CHECKPOINT_IDENTITY:
        issues.append(
            ReadinessIssue(
                "checkpoint_identity_unverified",
                "checkpoint identity is not in this adapter's verified provenance manifest",
            )
        )

    if config.checkpoint_sha256 is None:
        issues.append(
            ReadinessIssue(
                "checkpoint_digest_missing",
                "configure the published SHA-256 digest for the primary DiT checkpoint",
            )
        )
    elif not _SHA256_PATTERN.fullmatch(config.checkpoint_sha256):
        issues.append(
            ReadinessIssue(
                "checkpoint_digest_invalid",
                "checkpoint SHA-256 must be 64 lowercase hexadecimal characters",
            )
        )
    elif (
        config.checkpoint_sha256
        != dict((weight.relative_path, weight.sha256) for weight in OFFICIAL_WEIGHT_DIGESTS)[
            PRIMARY_WEIGHT_PATH
        ]
    ):
        issues.append(
            ReadinessIssue(
                "checkpoint_digest_unverified",
                "checkpoint SHA-256 is not published by this adapter's pinned provenance",
            )
        )


def _check_provenance(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    if config.provenance_url is None:
        issues.append(
            ReadinessIssue(
                "provenance_missing",
                "configure the authoritative HTTPS model provenance URL",
            )
        )
        return
    parsed = urlparse(config.provenance_url)
    if parsed.scheme != "https" or not parsed.hostname:
        issues.append(
            ReadinessIssue(
                "provenance_invalid",
                "model provenance must be an authoritative HTTPS URL",
            )
        )
    elif config.provenance_url != OFFICIAL_PROVENANCE_URL:
        issues.append(
            ReadinessIssue(
                "provenance_unverified",
                "model provenance URL does not identify this adapter's immutable official revision",
            )
        )


def _check_upstream_commit(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    if config.upstream_commit != PINNED_UPSTREAM_COMMIT:
        issues.append(
            ReadinessIssue(
                "upstream_commit_mismatch",
                f"adapter supports only ACE-Step commit {PINNED_UPSTREAM_COMMIT}",
            )
        )
        return
    checkout_commit = upstream_checkout_commit(config.project_root)
    if checkout_commit is None:
        issues.append(
            ReadinessIssue(
                "upstream_checkout_unverified",
                "project_root must be a git checkout of the pinned ACE-Step commit",
            )
        )
    elif checkout_commit != PINNED_UPSTREAM_COMMIT:
        issues.append(
            ReadinessIssue(
                "upstream_checkout_mismatch",
                f"ACE-Step checkout must be at commit {PINNED_UPSTREAM_COMMIT}",
            )
        )
    else:
        checkout_clean = upstream_checkout_is_clean(config.project_root)
        if checkout_clean is None:
            issues.append(
                ReadinessIssue(
                    "upstream_checkout_unverified",
                    "could not verify that the pinned ACE-Step checkout is clean",
                )
            )
        elif not checkout_clean:
            issues.append(
                ReadinessIssue(
                    "upstream_checkout_dirty",
                    "ACE-Step checkout has local changes and does not match the pinned source",
                )
            )


def _check_weight_manifest(config: AceStepConfig, issues: list[ReadinessIssue]) -> None:
    weights = {weight.relative_path: weight.sha256 for weight in config.verified_weights}
    published_weights = {weight.relative_path: weight.sha256 for weight in OFFICIAL_WEIGHT_DIGESTS}
    missing_manifest_entries = sorted(
        set(REQUIRED_WEIGHT_PATHS) - set(weights), key=lambda path: path.as_posix()
    )
    if missing_manifest_entries:
        missing = ", ".join(path.as_posix() for path in missing_manifest_entries)
        issues.append(
            ReadinessIssue(
                "weight_manifest_incomplete",
                f"verified weight manifest is missing: {missing}",
            )
        )

    primary_manifest_digest = weights.get(PRIMARY_WEIGHT_PATH)
    if (
        config.checkpoint_sha256 is not None
        and primary_manifest_digest is not None
        and config.checkpoint_sha256 != primary_manifest_digest
    ):
        issues.append(
            ReadinessIssue(
                "checkpoint_digest_mismatch",
                "primary checkpoint digest does not match its verified weight manifest entry",
            )
        )

    for relative_path in REQUIRED_WEIGHT_PATHS:
        expected_digest = weights.get(relative_path)
        if expected_digest is None:
            continue
        if not _SHA256_PATTERN.fullmatch(expected_digest):
            issues.append(
                ReadinessIssue(
                    "weight_digest_invalid",
                    f"invalid SHA-256 digest for {relative_path.as_posix()}",
                )
            )
            continue
        if expected_digest != published_weights[relative_path]:
            issues.append(
                ReadinessIssue(
                    "weight_digest_unverified",
                    f"weight digest is not published for {relative_path.as_posix()}",
                )
            )
            continue
        weight_path = config.checkpoints_dir / relative_path
        if not weight_path.is_file():
            issues.append(
                ReadinessIssue(
                    "checkpoint_file_missing",
                    f"verified checkpoint file is missing: {weight_path}",
                )
            )
            continue
        if checkpoint_sha256(weight_path) != expected_digest:
            issues.append(
                ReadinessIssue(
                    "checkpoint_digest_mismatch",
                    f"checkpoint digest mismatch: {weight_path}",
                )
            )
