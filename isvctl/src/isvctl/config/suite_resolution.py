# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve one platform or plain suite to a provider configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from isvctl.config.merger import merge_yaml_files


class SuiteResolutionError(Exception):
    """Raised when a suite selection cannot be resolved unambiguously."""


@dataclass(frozen=True)
class ResolvedSuite:
    """A provider configuration selected for one logical suite."""

    config_path: Path
    name: str
    platform: str | None


def _normalize_name(value: str) -> str:
    """Normalize CLI and filename spellings to catalog suite names."""
    normalized = value.strip().lower().replace("-", "_")
    return "kubernetes" if normalized == "k8s" else normalized


def platform_vocabulary(configs_root: Path) -> frozenset[str]:
    """Return declarable capabilities from canonical platform suite YAML."""
    platforms: set[str] = set()
    for path in (configs_root / "suites").glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        platform = (data.get("tests") or {}).get("platform") if isinstance(data, dict) else None
        if isinstance(platform, str) and platform:
            platforms.add(_normalize_name(platform))
    return frozenset(platforms)


def parse_capabilities(value: str | None, configs_root: Path) -> set[str] | None:
    """Parse a comma-separated capability context using platform suite names."""
    if value is None:
        return None
    capabilities = {_normalize_name(item) for item in value.split(",") if item.strip()}
    allowed = platform_vocabulary(configs_root)
    unknown = sorted(capabilities - allowed)
    if unknown:
        raise SuiteResolutionError(
            f"Unknown or non-declarable capabilities: {', '.join(unknown)}. "
            f"Available capabilities: {', '.join(sorted(allowed)) or '(none)'}."
        )
    return capabilities


def _raw_imports(config_path: Path) -> list[str]:
    """Return import paths declared directly by a provider config."""
    try:
        data: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SuiteResolutionError(f"Failed to read {config_path}: {exc}") from exc
    value = data.get("import") if isinstance(data, dict) else None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _suite_name(config_path: Path, declarable: frozenset[str]) -> tuple[str, str | None]:
    """Return the logical suite name and optional platform key for a config."""
    merged = merge_yaml_files([config_path])
    tests = merged.get("tests") or {}
    platform = tests.get("platform") if isinstance(tests, dict) else None
    if isinstance(platform, str) and _normalize_name(platform) in declarable:
        normalized = _normalize_name(platform)
        return normalized, normalized

    suite_imports = [Path(value).stem for value in _raw_imports(config_path) if "suites" in Path(value).parts]
    if len(suite_imports) > 1:
        raise SuiteResolutionError(
            f"Config {config_path} imports multiple suites ({', '.join(suite_imports)}); use --config/-f."
        )
    name = suite_imports[0] if suite_imports else config_path.stem
    return _normalize_name(name), None


def resolve_suite(provider: str, suite: str, *, configs_root: Path) -> ResolvedSuite:
    """Resolve exactly one provider config for a platform or plain suite."""
    config_dir = configs_root / "providers" / provider / "config"
    if not config_dir.is_dir():
        raise SuiteResolutionError(f"Provider {provider!r} has no config directory at {config_dir}.")

    requested = _normalize_name(suite)
    declarable = platform_vocabulary(configs_root)
    classified = [(path, *_suite_name(path, declarable)) for path in sorted(config_dir.glob("*.yaml"))]
    matches = [item for item in classified if item[1] == requested]
    if not matches:
        available = sorted({name for _, name, _ in classified})
        raise SuiteResolutionError(
            f"Provider {provider!r} has no {requested!r} suite. Available suites: {', '.join(available) or '(none)'}."
        )
    if len(matches) > 1:
        paths = ", ".join(str(path) for path, _, _ in matches)
        raise SuiteResolutionError(
            f"Provider {provider!r} has multiple {requested!r} suite configs ({paths}). Disambiguate with --config/-f."
        )
    path, name, platform = matches[0]
    return ResolvedSuite(config_path=path, name=name, platform=platform)
