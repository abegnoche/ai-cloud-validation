# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for K8sPlatformValidatorBase."""

import json
from pathlib import Path
from string import Template
from unittest.mock import MagicMock, patch

from isvtest.workloads.k8s_platform_validator import (
    DEFAULT_NAMESPACE,
    DEFAULT_TEST_SUITE,
    DEFAULT_TIMEOUT,
    MANIFEST_PATH,
    VALID_TEST_SUITES,
    K8sPlatformValidatorBase,
    K8sPlatformValidatorFunctional,
    K8sPlatformValidatorNvstorage,
    K8sPlatformValidatorPerformance,
)

GO_TEST_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "go_test_demo_output.txt"


class TestK8sPlatformValidatorBaseInit:
    """Test K8sPlatformValidatorBase initialization."""

    def test_default_config(self) -> None:
        workload = K8sPlatformValidatorBase()
        assert workload.config == {}
        assert workload._job_name is None

    def test_custom_config(self) -> None:
        config = {
            "test_suite": "performance",
            "cloud_provider": "gcp",
            "timeout": 7200,
            "image": "registry.example.com/my-tests:1.0",
        }
        workload = K8sPlatformValidatorBase(config=config)
        assert workload.config == config

    def test_markers(self) -> None:
        assert "workload" in K8sPlatformValidatorBase.markers
        assert "kubernetes" in K8sPlatformValidatorBase.markers
        assert "l2" in K8sPlatformValidatorBase.markers
        assert "slow" in K8sPlatformValidatorBase.markers

    def test_default_timeout(self) -> None:
        assert K8sPlatformValidatorBase.timeout == DEFAULT_TIMEOUT


class TestConvenienceSubclasses:
    """Test the per-suite convenience subclasses."""

    def test_functional_defaults(self) -> None:
        workload = K8sPlatformValidatorFunctional()
        assert workload.config.get("test_suite") == "functional"

    def test_functional_preserves_other_config(self) -> None:
        config = {"cloud_provider": "aws", "timeout": 1800, "image": "img:1"}
        workload = K8sPlatformValidatorFunctional(config=config)
        assert workload.config.get("test_suite") == "functional"
        assert workload.config.get("cloud_provider") == "aws"
        assert workload.config.get("timeout") == 1800
        assert workload.config.get("image") == "img:1"

    def test_performance_defaults(self) -> None:
        workload = K8sPlatformValidatorPerformance()
        assert workload.config.get("test_suite") == "performance"
        assert workload.config.get("timeout") == 10800

    def test_performance_class_timeout(self) -> None:
        assert K8sPlatformValidatorPerformance.timeout == 10800

    def test_nvstorage_defaults(self) -> None:
        workload = K8sPlatformValidatorNvstorage()
        assert workload.config.get("test_suite") == "nvstorage"

    def test_nvstorage_preserves_other_config(self) -> None:
        config = {"cloud_provider": "aws", "image": "img:1"}
        workload = K8sPlatformValidatorNvstorage(config=config)
        assert workload.config.get("test_suite") == "nvstorage"
        assert workload.config.get("cloud_provider") == "aws"


class TestJobManifestTemplate:
    """Test the Job manifest template."""

    def test_manifest_file_exists(self) -> None:
        assert MANIFEST_PATH.exists(), f"Manifest file not found: {MANIFEST_PATH}"

    def test_template_has_required_placeholders(self) -> None:
        content = MANIFEST_PATH.read_text()
        for placeholder in (
            "${JOB_NAME}",
            "${NAMESPACE}",
            "${TEST_SUITE}",
            "${CLOUD_PROVIDER}",
            "${IMAGE}",
            "${ACTIVE_DEADLINE_SECONDS}",
            "${SERVICE_ACCOUNT}",
            "${PULL_SECRET}",
            "${TEST_ARGS}",
        ):
            assert placeholder in content, f"Missing placeholder {placeholder} in manifest"

    def test_template_substitution(self) -> None:
        content = MANIFEST_PATH.read_text()
        template = Template(content)
        test_args = json.dumps(["-test.timeout", "55m", "-test.v"])
        manifest = template.substitute(
            JOB_NAME="test-job",
            NAMESPACE="test-ns",
            TEST_SUITE="functional",
            ACTIVE_DEADLINE_SECONDS=3600,
            SERVICE_ACCOUNT="test-sa",
            PULL_SECRET="test-secret",
            IMAGE="test-image:latest",
            CLOUD_PROVIDER="aws",
            TEST_ARGS=test_args,
        )
        assert "test-job" in manifest
        assert "test-ns" in manifest
        assert "functional" in manifest
        assert "aws" in manifest
        assert "test-image:latest" in manifest
        assert "apiVersion: batch/v1" in manifest
        assert "kind: Job" in manifest


class TestReportResults:
    """Test result parsing logic against canned Go test output."""

    def test_parse_pass_results(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        logs = """
=== RUN   TestGPU_Smi_AllNodes
--- PASS: TestGPU_Smi_AllNodes (15.23s)
=== RUN   TestPod_Creation
--- PASS: TestPod_Creation (5.12s)
PASS
"""
        workload._report_results(logs, "functional")
        assert workload._passed is True
        assert "2 passed" in workload._output

    def test_parse_fail_results(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        logs = """
=== RUN   TestGPU_Smi_AllNodes
--- PASS: TestGPU_Smi_AllNodes (15.23s)
=== RUN   TestPod_Creation
--- FAIL: TestPod_Creation (5.12s)
    pod_test.go:45: expected pod to be running
FAIL
"""
        workload._report_results(logs, "functional")
        assert workload._passed is False
        assert "1 passed" in workload._error
        assert "1 failed" in workload._error
        assert "TestPod_Creation" in workload._error

    def test_parse_skip_results(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        logs = """
=== RUN   TestGPU_Smi_AllNodes
--- PASS: TestGPU_Smi_AllNodes (15.23s)
=== RUN   TestEFA_Check
--- SKIP: TestEFA_Check (0.01s)
    efa_test.go:30: EFA not available, skipping
PASS
"""
        workload._report_results(logs, "functional")
        assert workload._passed is True
        assert "1 passed" in workload._output
        assert "1 skipped" in workload._output

    def test_parse_panic_timeout(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        logs = """
=== RUN   TestCudaPerformance
--- PASS: TestCudaPerformance (0.19s)
=== RUN   TestNcclPerformance
panic: test timed out after 14m0s
     running tests:
             TestNcclPerformance (14m0s)

goroutine 110 [running]:
testing.(*M).startAlarm.func1()
     /usr/local/go/src/testing/testing.go:2682 +0x345
"""
        workload._report_results(logs, "performance")
        assert workload._passed is False
        assert "PANICKED" in workload._error
        assert "timeout" in workload._error.lower() or "runtime error" in workload._error.lower()

    def test_parse_panic_runtime_error(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        logs = """
=== RUN   TestGPU_Smi_AllNodes
--- PASS: TestGPU_Smi_AllNodes (15.23s)
=== RUN   TestBadCode
panic: runtime error: index out of range [5] with length 3

goroutine 1 [running]:
main.badFunction()
     /app/bad.go:10 +0x45
"""
        workload._report_results(logs, "functional")
        assert workload._passed is False
        assert "PANICKED" in workload._error


class TestRealGoOutputFixture:
    """Pipe captured `go test -v` output from isvtest/examples/go-test-demo through the parser.

    This proves the parser handles **real** Go test output (subtests, durations,
    failure bodies, t.Skip()), not just hand-written strings. The fixture is
    regenerated by running ``isvtest/examples/go-test-demo/regen_fixture.sh``.
    """

    def test_fixture_exists(self) -> None:
        assert GO_TEST_FIXTURE_PATH.exists(), (
            f"Fixture missing at {GO_TEST_FIXTURE_PATH}. "
            f"Run isvtest/examples/go-test-demo/regen_fixture.sh to regenerate it."
        )

    def test_parser_against_real_go_output(self) -> None:
        logs = GO_TEST_FIXTURE_PATH.read_text()
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        results = workload._parse_go_test_results(logs)

        names = {r.name for r in results}
        # Top-level tests from the demo
        assert "TestDemoPass" in names
        assert "TestDemoFail" in names
        assert "TestDemoSkip" in names
        # Subtests are also captured (slash-delimited)
        assert any("/" in r.name for r in results), "Expected at least one Go subtest in fixture"

        by_name = {r.name: r for r in results}
        assert by_name["TestDemoPass"].passed is True
        assert by_name["TestDemoPass"].skipped is False
        assert by_name["TestDemoFail"].passed is False
        assert by_name["TestDemoFail"].skipped is False
        assert by_name["TestDemoFail"].message != ""
        assert by_name["TestDemoSkip"].skipped is True
        assert by_name["TestDemoSkip"].passed is False

        # Every parsed test should have a non-None duration since `go test -v`
        # always emits one.
        assert all(r.duration is not None for r in results)

    def test_full_report_against_real_go_output(self) -> None:
        logs = GO_TEST_FIXTURE_PATH.read_text()
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        workload._report_results(logs, "functional")
        # The demo intentionally has one failing test, so the overall verdict
        # must be FAIL.
        assert workload._passed is False
        assert "TestDemoFail" in workload._error

    def test_subtests_recorded_against_real_go_output(self) -> None:
        """Real `go test -v` output -> one pytest-subtest entry per top-level Go test.

        This is the end-to-end check: it proves the workload's `_report_results`
        translates raw Go test stdout into the same `_subtest_results` list that
        `BaseValidation.report_subtest` populates for pytest's subtest fixture,
        which in turn drives the per-test rows in the JUnit XML and pytest
        terminal summary.
        """
        logs = GO_TEST_FIXTURE_PATH.read_text()
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        workload._report_results(logs, "functional")

        recorded = {r["name"]: r for r in workload._subtest_results}
        # Subtests with "/" in the name (Go's t.Run children) must NOT be
        # reported again at the top level, to avoid double-counting in pytest.
        assert all("/" not in name for name in recorded), recorded

        assert recorded["TestDemoPass"]["passed"] is True
        assert recorded["TestDemoPass"]["skipped"] is False
        assert recorded["TestDemoFail"]["passed"] is False
        assert recorded["TestDemoFail"]["skipped"] is False
        assert recorded["TestDemoSkip"]["passed"] is False
        assert recorded["TestDemoSkip"]["skipped"] is True
        assert recorded["TestDemoSubtests"]["passed"] is True
        assert all(r["duration"] is not None for r in recorded.values())


class TestValidation:
    """Test validation logic."""

    def test_missing_image(self) -> None:
        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws"})

        with patch.object(workload, "_check_infrastructure", return_value=True):
            workload.run()

        assert workload._passed is False
        assert "image is required" in workload._error

    def test_missing_cloud_provider(self) -> None:
        workload = K8sPlatformValidatorBase(config={"image": "img:1"})

        with patch.object(workload, "_check_infrastructure", return_value=True):
            workload.run()

        assert workload._passed is False
        assert "cloud_provider is required" in workload._error

    def test_invalid_test_suite(self) -> None:
        workload = K8sPlatformValidatorBase(
            config={
                "cloud_provider": "aws",
                "image": "img:1",
                "test_suite": "invalid_suite",
            }
        )

        with patch.object(workload, "_check_infrastructure", return_value=True):
            workload.run()

        assert workload._passed is False
        assert "Invalid test_suite" in workload._error

    def test_valid_test_suites(self) -> None:
        for suite in VALID_TEST_SUITES:
            workload = K8sPlatformValidatorBase(
                config={
                    "cloud_provider": "aws",
                    "image": "img:1",
                    "test_suite": suite,
                    "skip_infrastructure_check": True,
                }
            )
            # _create_job returns False -> run() exits before submitting; we
            # just need to confirm we got past suite validation.
            with patch.object(workload, "_create_job", return_value=False):
                workload.run()
                if workload._error:
                    assert "Invalid test_suite" not in workload._error

    def test_default_test_suite_constant(self) -> None:
        assert DEFAULT_TEST_SUITE in VALID_TEST_SUITES


class TestCheckInfrastructure:
    """Test infrastructure check logic."""

    @patch("isvtest.workloads.k8s_platform_validator.run_kubectl")
    def test_namespace_not_found(self, mock_run_kubectl: MagicMock) -> None:
        mock_run_kubectl.return_value = MagicMock(returncode=1, stderr="not found")

        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        result = workload._check_infrastructure("test-ns", "test-sa", "test-secret")

        assert result is False
        assert "Namespace 'test-ns' not found" in workload._error

    @patch("isvtest.workloads.k8s_platform_validator.run_kubectl")
    def test_service_account_not_found(self, mock_run_kubectl: MagicMock) -> None:
        def kubectl_side_effect(args: list[str]) -> MagicMock:
            if "namespace" in args:
                return MagicMock(returncode=0)
            elif "serviceaccount" in args:
                return MagicMock(returncode=1, stderr="not found")
            return MagicMock(returncode=0)

        mock_run_kubectl.side_effect = kubectl_side_effect

        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        result = workload._check_infrastructure("test-ns", "test-sa", "test-secret")

        assert result is False
        assert "ServiceAccount 'test-sa' not found" in workload._error

    @patch("isvtest.workloads.k8s_platform_validator.run_kubectl")
    def test_pull_secret_warning_only(self, mock_run_kubectl: MagicMock) -> None:
        def kubectl_side_effect(args: list[str]) -> MagicMock:
            if "namespace" in args:
                return MagicMock(returncode=0)
            elif "serviceaccount" in args:
                return MagicMock(returncode=0)
            elif "secret" in args:
                return MagicMock(returncode=1, stderr="not found")
            return MagicMock(returncode=0)

        mock_run_kubectl.side_effect = kubectl_side_effect

        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        result = workload._check_infrastructure("test-ns", "test-sa", "test-secret")

        assert result is True

    @patch("isvtest.workloads.k8s_platform_validator.run_kubectl")
    def test_all_infrastructure_exists(self, mock_run_kubectl: MagicMock) -> None:
        mock_run_kubectl.return_value = MagicMock(returncode=0)

        workload = K8sPlatformValidatorBase(config={"cloud_provider": "aws", "image": "img:1"})
        result = workload._check_infrastructure("test-ns", "test-sa", "test-secret")

        assert result is True


class TestConstants:
    """Test module constants."""

    def test_default_namespace(self) -> None:
        assert DEFAULT_NAMESPACE == "dgxc-validation"

    def test_default_timeout(self) -> None:
        assert DEFAULT_TIMEOUT == 3600

    def test_default_test_suite(self) -> None:
        assert DEFAULT_TEST_SUITE == "functional"

    def test_valid_test_suites(self) -> None:
        assert "nvstorage" in VALID_TEST_SUITES
        assert "functional" in VALID_TEST_SUITES
        assert "performance" in VALID_TEST_SUITES
        assert "nmc" in VALID_TEST_SUITES
        # The previous name from the GitLab snapshot must not creep back in.
        assert "nmcstorage" not in VALID_TEST_SUITES
