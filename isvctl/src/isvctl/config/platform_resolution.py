# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Platform/module resolution for ``--platform`` and ``--module`` selection.

Sibling of :mod:`isvctl.config.label_discovery`. Classifies a provider's configs
by their effective ``tests`` axis key (inherited through ``import:``): a config
that declares ``module:`` is an operational concern; otherwise its ``platform:``
marks a platform suite (service line). Plans which configs to run:

* ``--platform <platform>`` runs the whole matrix column: the one config whose
  ``platform`` is ``<platform>`` (and which declares no ``module``) first, then
  every ``module:`` config, each with platform-scoped exclude labels so checks
  tagged with a *different* platform are skipped.
* ``--module <mod>`` runs a single config declaring ``module: <mod>``.

Classification is by the axis key, never by filename: an ``aws/config/eks.yaml``
that imports ``k8s.yaml`` inherits ``platform: kubernetes`` and is a platform suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from isvctl.config.merger import merge_yaml_files

PLATFORM_SUITE_KIND = "platform"
MODULE_KIND = "module"
# CLI aliases accepted for platform names, mirroring the orchestrator's
# ``k8s`` -> ``kubernetes`` normalization.
PLATFORM_ALIASES = {"k8s": "kubernetes"}


class PlatformResolutionError(Exception):
    """Raised when a platform/module selection cannot be resolved."""


@dataclass(frozen=True)
class ClassifiedConfig:
    """A provider config classified by its effective kind and platform."""

    config_path: Path
    kind: str
    platform: str


@dataclass(frozen=True)
class PlannedRun:
    """A single config to run as part of a ``--platform``/``--module`` selection."""

    config_path: Path
    role: str  # "platform" or "module"
    platform: str
    exclude_labels: tuple[str, ...] = ()


def _effective_kind_and_platform(config_path: Path) -> tuple[str | None, str | None]:
    """Return the ``(kind, platform)`` a config resolves to after imports.

    A config that declares ``tests.module`` is a module (its module value is the
    platform); otherwise ``tests.platform`` marks it a platform suite.
    """
    merged = merge_yaml_files([config_path])
    tests = merged.get("tests") or {}
    if not isinstance(tests, dict):
        return None, None
    module = tests.get("module")
    if isinstance(module, str) and module:
        return MODULE_KIND, module
    platform = tests.get("platform")
    if isinstance(platform, str) and platform:
        return PLATFORM_SUITE_KIND, platform
    return None, None


def platform_label_universe(configs_root: Path) -> frozenset[str]:
    """Return every platform label defined by the shipped platform suites.

    Derived from ``configs_root/suites`` (not the provider's configs) so exclusion
    is stable even when a provider is missing a platform config. A platform suite
    is one that declares ``platform`` and no ``module``.
    """
    suites_dir = configs_root / "suites"
    universe: set[str] = set()
    for path in sorted(suites_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        tests = (data or {}).get("tests", {})
        if not isinstance(tests, dict):
            continue
        if tests.get("module"):
            continue
        platform = tests.get("platform")
        if isinstance(platform, str) and platform:
            universe.add(platform)
    return frozenset(universe)


def _provider_config_dir(provider: str, configs_root: Path) -> Path:
    """Return a provider's config directory, erroring if it is absent."""
    provider_config_dir = configs_root / "providers" / provider / "config"
    if not provider_config_dir.is_dir():
        raise PlatformResolutionError(f"Provider {provider!r} has no config directory at {provider_config_dir}.")
    return provider_config_dir


def classify_provider_configs(provider: str, *, configs_root: Path) -> list[ClassifiedConfig]:
    """Classify every config under a provider by its effective kind + platform.

    Raises:
        PlatformResolutionError: If a config declares no (or an invalid) kind.
    """
    provider_config_dir = _provider_config_dir(provider, configs_root)
    classified: list[ClassifiedConfig] = []
    for config_path in sorted(provider_config_dir.glob("*.yaml")):
        kind, platform = _effective_kind_and_platform(config_path)
        if kind not in (PLATFORM_SUITE_KIND, MODULE_KIND) or not platform:
            raise PlatformResolutionError(
                f"Config {config_path} declares neither tests.platform nor tests.module; "
                f"every provider config must inherit a platform or module suite "
                f"via import (or declare one of these keys directly)."
            )
        classified.append(ClassifiedConfig(config_path=config_path, kind=kind, platform=platform))
    return classified


def _available_platforms(classified: list[ClassifiedConfig]) -> list[str]:
    """Return the sorted platform values a provider exposes."""
    return sorted({c.platform for c in classified if c.kind == PLATFORM_SUITE_KIND})


def _available_modules(classified: list[ClassifiedConfig]) -> list[str]:
    """Return the sorted module platforms a provider exposes."""
    return sorted({c.platform for c in classified if c.kind == MODULE_KIND})


def plan_platform_run(provider: str, platform: str, *, configs_root: Path) -> list[PlannedRun]:
    """Plan the configs to run for ``--platform <platform>``.

    The platform config runs first (no excludes); each module config follows
    with ``exclude_labels`` = every *other* platform label, so module checks
    tagged for a different platform are skipped under this column.

    Raises:
        PlatformResolutionError: On unknown/duplicate platform configs.
    """
    normalized = PLATFORM_ALIASES.get(platform, platform)
    classified = classify_provider_configs(provider, configs_root=configs_root)

    platform_configs = [c for c in classified if c.kind == PLATFORM_SUITE_KIND and c.platform == normalized]
    if not platform_configs:
        available = _available_platforms(classified)
        raise PlatformResolutionError(
            f"Provider {provider!r} has no {normalized!r} platform config. "
            f"Available platforms: {', '.join(available) or '(none)'}."
        )
    if len(platform_configs) > 1:
        paths = ", ".join(str(c.config_path) for c in platform_configs)
        raise PlatformResolutionError(
            f"Provider {provider!r} has multiple {normalized!r} platform configs ({paths}). "
            f"Disambiguate with --config/-f."
        )

    universe = platform_label_universe(configs_root)
    exclude_labels = tuple(sorted(universe - {normalized}))

    runs: list[PlannedRun] = [
        PlannedRun(
            config_path=platform_configs[0].config_path,
            role=PLATFORM_SUITE_KIND,
            platform=normalized,
        )
    ]
    for module_config in sorted((c for c in classified if c.kind == MODULE_KIND), key=lambda c: c.config_path):
        runs.append(
            PlannedRun(
                config_path=module_config.config_path,
                role=MODULE_KIND,
                platform=module_config.platform,
                exclude_labels=exclude_labels,
            )
        )
    return runs


def resolve_module_config(provider: str, module: str, *, configs_root: Path) -> PlannedRun:
    """Resolve the single ``kind: module`` config for ``--module <module>``.

    Runs standalone (no platform context), so no platform excludes apply.

    Raises:
        PlatformResolutionError: On unknown/duplicate module configs.
    """
    classified = classify_provider_configs(provider, configs_root=configs_root)
    module_configs = [c for c in classified if c.kind == MODULE_KIND and c.platform == module]
    if not module_configs:
        available = _available_modules(classified)
        raise PlatformResolutionError(
            f"Provider {provider!r} has no {module!r} module config. "
            f"Available modules: {', '.join(available) or '(none)'}."
        )
    if len(module_configs) > 1:
        paths = ", ".join(str(c.config_path) for c in module_configs)
        raise PlatformResolutionError(
            f"Provider {provider!r} has multiple {module!r} module configs ({paths}). Disambiguate with --config/-f."
        )
    return PlannedRun(config_path=module_configs[0].config_path, role=MODULE_KIND, platform=module)
