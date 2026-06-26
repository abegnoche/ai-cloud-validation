# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provider-scoped label discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from isvtest.core.resolution import parse_validations

from isvctl.config.merger import merge_yaml_files


@dataclass(frozen=True)
class MatchedCheck:
    """A validation check that matched requested labels."""

    category: str
    name: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class ProviderConfigMatch:
    """A provider config selected by label discovery."""

    config_path: Path
    matched_checks: tuple[MatchedCheck, ...]


def discover_provider_label_configs(
    provider: str,
    labels: list[str],
    *,
    configs_root: Path,
) -> list[ProviderConfigMatch]:
    """Return provider configs whose resolved validation wiring matches all labels."""
    requested = {label for label in labels if label}
    provider_config_dir = configs_root / "providers" / provider / "config"
    matches: list[ProviderConfigMatch] = []

    for config_path in sorted(provider_config_dir.glob("*.yaml")):
        merged = merge_yaml_files([config_path])
        raw_validations = (merged.get("tests") or {}).get("validations") or {}
        matched_checks = tuple(
            MatchedCheck(category=entry.category, name=entry.name, labels=entry.labels)
            for entry in parse_validations(raw_validations)
            if requested.issubset(entry.labels)
        )
        if matched_checks:
            matches.append(ProviderConfigMatch(config_path=config_path, matched_checks=matched_checks))
    return matches
