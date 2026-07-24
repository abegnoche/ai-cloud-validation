# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for provider suite selection and capability parsing."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from isvctl.config.schema import RunConfig
from isvctl.config.suite_resolution import (
    SuiteResolutionError,
    parse_capability,
    resolve_suite,
)


def _write_catalog(root: Path) -> None:
    """Write one platform suite, one plain suite, and provider imports."""
    suites = root / "suites"
    configs = root / "providers" / "acme" / "config"
    suites.mkdir(parents=True)
    configs.mkdir(parents=True)
    (suites / "k8s.yaml").write_text("tests:\n  platform: kubernetes\n  validations: {}\n")
    (suites / "storage.yaml").write_text("tests:\n  validations: {}\n")
    (configs / "eks.yaml").write_text("import: ../../../suites/k8s.yaml\ncommands: {}\n")
    (configs / "storage.yaml").write_text("import: ../../../suites/storage.yaml\ncommands: {}\n")


def test_one_suite_flag_resolves_platform_and_plain_suites(tmp_path: Path) -> None:
    """The same selector resolves both suite kinds by effective YAML identity."""
    _write_catalog(tmp_path)

    platform = resolve_suite("acme", "kubernetes", configs_root=tmp_path)
    plain = resolve_suite("acme", "storage", configs_root=tmp_path)

    assert platform.config_path.name == "eks.yaml"
    assert platform.platform == "kubernetes"
    assert plain.config_path.name == "storage.yaml"
    assert plain.platform is None


def test_capability_uses_catalog_vocabulary(tmp_path: Path) -> None:
    """An unknown capability is rejected while omitted context disables filtering."""
    _write_catalog(tmp_path)

    assert parse_capability(None, tmp_path) is None
    assert parse_capability("k8s", tmp_path) == "kubernetes"
    with pytest.raises(SuiteResolutionError, match="non-declarable capability: compute"):
        parse_capability("compute", tmp_path)
    with pytest.raises(SuiteResolutionError, match="single platform"):
        parse_capability("kubernetes,vm", tmp_path)


def test_platform_suites_reject_requires_and_unknown_platforms() -> None:
    """Platform placement is its obligation; it cannot declare check requirements."""
    validation = {"sample": {"checks": {"PlainCheck": {"requires": []}}}}

    with pytest.raises(ValidationError, match="requires is not allowed in platform suites"):
        RunConfig.model_validate({"tests": {"platform": "kubernetes", "validations": validation}})
    with pytest.raises(ValidationError, match=r"tests\.platform must be one of"):
        RunConfig.model_validate({"tests": {"platform": "compute", "validations": {}}})


def test_plain_suite_rejects_unknown_requires_vocabulary() -> None:
    """`test validate` catches a bad `requires` value, not just a run does."""
    validation = {"sample": {"checks": {"PlainCheck": {"requires": ["compute"]}}}}
    with pytest.raises(ValidationError, match="requires must be a list containing only"):
        RunConfig.model_validate({"tests": {"validations": validation}})


def test_plain_suite_rejects_duplicate_requires() -> None:
    """Duplicate requirements are rejected at schema-validation time."""
    validation = {"sample": {"checks": {"PlainCheck": {"requires": ["vm", "vm"]}}}}
    with pytest.raises(ValidationError, match="requires must not contain duplicates"):
        RunConfig.model_validate({"tests": {"validations": validation}})


def test_plain_suite_accepts_valid_requires() -> None:
    """A well-formed requires list passes schema validation."""
    validation = {"sample": {"checks": {"PlainCheck": {"requires": ["vm", "bare_metal"]}}}}
    RunConfig.model_validate({"tests": {"validations": validation}})
