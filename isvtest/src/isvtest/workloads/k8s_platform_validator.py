# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""K8s Platform Validator workload for running Go-based e2e tests.

Deploys a container image whose entrypoint runs a Go test binary (built with
``go test -c``) as a Kubernetes Job, then parses Go's standard test output
(``=== RUN``, ``--- PASS:``, ``--- FAIL:``, ``--- SKIP:``) and reports each
top-level Go test as a pytest subtest so it shows up in the pytest summary and
JUnit XML alongside native pytest tests.

The container image is **required** config: this workload is provider-neutral
and does not bundle a default image. NVIDIA-internal users typically point at
``nvcr.io/nv-ngc-devops/k8s-platform-validator``; open-source users can build
the example image at ``isvtest/examples/go-test-demo/`` and use that, or supply their
own Go-test container.
"""

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, ClassVar

from isvtest.core.k8s import (
    delete_job,
    get_job_pods,
    get_kubectl_command,
    get_pod_logs,
    run_kubectl,
    wait_for_job_completion,
)
from isvtest.core.runners import Runner
from isvtest.core.workload import BaseWorkloadCheck

DEFAULT_NAMESPACE = "dgxc-validation"
DEFAULT_TIMEOUT = 3600  # 1 hour
DEFAULT_TEST_SUITE = "functional"
VALID_TEST_SUITES = ("functional", "performance", "nmc", "nvstorage")

MANIFEST_PATH = Path(__file__).parent / "manifests" / "k8s" / "platform_validator_job.yaml"


@dataclass
class GoTestResult:
    """Result of a single Go test parsed from test output."""

    name: str
    passed: bool
    skipped: bool
    duration: float | None
    message: str


class K8sPlatformValidatorBase(BaseWorkloadCheck):
    """Run a k8s-platform-validator-style Go test binary as a K8s Job.

    Submits a Job whose container runs a Go test binary, parses the binary's
    stdout, and reports each top-level Go test as a pytest subtest.

    Config options:
        image: Container image with a pre-built ``go test`` binary. Required.
            Example: ``nvcr.io/nv-ngc-devops/k8s-platform-validator:latest``.
        cloud_provider: Cloud provider passed to the container as
            ``CLOUD_PROVIDER`` env var (e.g. ``aws``, ``gcp``, ``azure``).
            Required (the upstream Go binary branches on it).
        test_suite: Suite selector passed to the container as ``TEST_SUITE``
            env var. One of: ``functional``, ``performance``, ``nmc``,
            ``nvstorage``. Default: ``functional``.
        timeout: Job ``activeDeadlineSeconds``, also enforces the
            ``-test.timeout`` arg. Default: 3600 (1 hour).
        namespace: Target namespace. Default: ``dgxc-validation``.
        service_account: ServiceAccount name. Default: ``k8s-platform-validator``.
        pull_secret: Image pull secret name.
            Default: ``nvidia-ngcuser-pull-secret``.
        cleanup: Delete the Job after completion. Default: ``True``.
        skip_infrastructure_check: Skip checking that the target namespace and
            ServiceAccount exist before submitting the Job. Default: ``False``.
        run_tests: Regex passed as ``-test.run`` (Go test selector).
            Example: ``"TestRealGPU|TestAllPods"``.
        skip_tests: Regex passed as ``-test.skip`` (Go test skip selector).
            Example: ``"TestEFA"``.

    Example config::

        - K8sPlatformValidatorBase:
            image: ghcr.io/example/my-go-tests:latest
            cloud_provider: aws
            test_suite: nvstorage
            timeout: 3600
    """

    description = "K8s platform validation - Go-based e2e tests run as a K8s Job"
    timeout: ClassVar[int] = DEFAULT_TIMEOUT
    markers: ClassVar[list[str]] = ["workload", "kubernetes", "l2", "slow"]

    _exclude_from_discovery: ClassVar[bool] = True

    def __init__(self, runner: Runner | None = None, config: dict[str, Any] | None = None) -> None:
        super().__init__(runner, config)
        self._job_name: str | None = None

    def run(self) -> None:
        """Execute the k8s-platform-validator tests."""
        image = self.config.get("image")
        test_suite = self.config.get("test_suite", DEFAULT_TEST_SUITE)
        cloud_provider = self.config.get("cloud_provider")
        timeout = int(self.config.get("timeout", DEFAULT_TIMEOUT))
        namespace = self.config.get("namespace", DEFAULT_NAMESPACE)
        service_account = self.config.get("service_account", "k8s-platform-validator")
        pull_secret = self.config.get("pull_secret", "nvidia-ngcuser-pull-secret")
        cleanup = self.config.get("cleanup", True)
        skip_infra_check = self.config.get("skip_infrastructure_check", False)
        run_tests = self.config.get("run_tests")
        skip_tests = self.config.get("skip_tests")

        if not image:
            self.set_failed(
                "image is required (e.g. 'nvcr.io/nv-ngc-devops/k8s-platform-validator:latest' "
                "or your own Go-test container built from isvtest/examples/go-test-demo/)"
            )
            return

        if not cloud_provider:
            self.set_failed("cloud_provider is required (aws, gcp, azure)")
            return

        if test_suite not in VALID_TEST_SUITES:
            self.set_failed(f"Invalid test_suite '{test_suite}'. Must be one of: {list(VALID_TEST_SUITES)}")
            return

        if not skip_infra_check and not self._check_infrastructure(namespace, service_account, pull_secret):
            return

        self._job_name = f"isvtest-validator-{test_suite}-{uuid.uuid4().hex[:8]}"

        # Leave a 1-minute buffer so the Go binary's own timeout fires slightly
        # before activeDeadlineSeconds, giving us a clean panic/log instead of
        # a hard kill.
        test_timeout_min = max(1, (timeout - 60) // 60)

        test_args = ["-test.timeout", f"{test_timeout_min}m", "-test.v"]
        if run_tests:
            test_args.extend(["-test.run", run_tests])
            self.log.info(f"Running only tests matching: {run_tests}")
        if skip_tests:
            test_args.extend(["-test.skip", skip_tests])
            self.log.info(f"Skipping tests matching: {skip_tests}")

        test_args_json = json.dumps(test_args)

        if not MANIFEST_PATH.exists():
            self.set_failed(f"Manifest file not found: {MANIFEST_PATH}")
            return

        template_content = MANIFEST_PATH.read_text()
        template = Template(template_content)
        manifest = template.substitute(
            JOB_NAME=self._job_name,
            NAMESPACE=namespace,
            TEST_SUITE=test_suite,
            ACTIVE_DEADLINE_SECONDS=timeout,
            SERVICE_ACCOUNT=service_account,
            PULL_SECRET=pull_secret,
            IMAGE=image,
            CLOUD_PROVIDER=cloud_provider,
            TEST_ARGS=test_args_json,
        )

        self.log.info(f"Starting k8s-platform-validator ({test_suite}) tests...")
        self.log.info(f"Job: {self._job_name}, Namespace: {namespace}, Timeout: {timeout}s")

        if not self._create_job(manifest, namespace):
            return

        logs = ""
        completed = False
        status = ""

        try:
            self.log.info(f"Waiting for job {self._job_name} to complete...")
            completed, status = wait_for_job_completion(self._job_name, namespace, timeout=timeout)
            logs = self._collect_logs(namespace)
        finally:
            # Clean up early so the pytest "PASSED" line lands right after the
            # subtest stream, not after kubectl chatter.
            if cleanup and self._job_name:
                self.log.info(f"Cleaning up job {self._job_name}...")
                delete_job(self._job_name, namespace, wait=False)

        if not completed:
            self.set_failed(
                f"Job timed out after {timeout}s. Status: {status}\n"
                f"Partial logs:\n{logs[:2000] if logs else 'No logs available'}"
            )
            return

        if status == "Complete":
            self._report_results(logs, test_suite)
        else:
            self.set_failed(f"Job failed with status: {status}\nLogs:\n{logs}")

    def _check_infrastructure(self, namespace: str, service_account: str, pull_secret: str) -> bool:
        """Check that required infrastructure exists.

        Returns ``True`` when the namespace and ServiceAccount both exist.
        A missing pull secret is logged as a warning, not a failure, since
        the image may be public.
        """
        result = run_kubectl(["get", "namespace", namespace])
        if result.returncode != 0:
            self.set_failed(
                f"Namespace '{namespace}' not found. "
                f"Create it (and the matching ServiceAccount) before running this workload."
            )
            return False

        result = run_kubectl(["get", "serviceaccount", service_account, "-n", namespace])
        if result.returncode != 0:
            self.set_failed(
                f"ServiceAccount '{service_account}' not found in namespace '{namespace}'. "
                f"Create it before running this workload."
            )
            return False

        result = run_kubectl(["get", "secret", pull_secret, "-n", namespace])
        if result.returncode != 0:
            self.log.warning(
                f"Pull secret '{pull_secret}' not found in namespace '{namespace}'. "
                f"Job may fail if the image is not public."
            )

        return True

    def _create_job(self, manifest: str, namespace: str) -> bool:
        """Create the Kubernetes Job."""
        kubectl_parts = get_kubectl_command()

        try:
            result = subprocess.run(
                kubectl_parts + ["apply", "-f", "-", "-n", namespace],
                input=manifest,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                self.set_failed(f"Failed to create job: {result.stderr}")
                return False
            self.log.info(f"Job {self._job_name} created successfully")
            self.log.info("")
            self.log.info("=" * 60)
            self.log.info("To stream live logs, run in another terminal:")
            self.log.info(f"  kubectl logs -f -l job-name={self._job_name} -n {namespace}")
            self.log.info("=" * 60)
            self.log.info("")
            return True
        except subprocess.TimeoutExpired:
            self.set_failed("Timeout creating job")
            return False
        except Exception as e:
            self.set_failed(f"Exception creating job: {e}")
            return False

    def _collect_logs(self, namespace: str) -> str:
        """Collect logs from the job's first pod."""
        if not self._job_name:
            return ""

        pods = get_job_pods(self._job_name, namespace)
        if not pods:
            self.log.warning(f"No pods found for job {self._job_name}")
            return ""

        return get_pod_logs(pods[0], namespace, timeout=60)

    def _parse_go_test_results(self, logs: str) -> list[GoTestResult]:
        """Parse Go test output and extract individual test results.

        Go test prints one ``--- STATUS: name (duration)`` line per test (and
        subtest), e.g.::

            === RUN   TestName
            --- PASS: TestName (1.23s)
            --- FAIL: TestName (0.50s)
            --- SKIP: TestName (0.00s)

        For subtests the name is ``TestParent/SubName``.
        """
        results: list[GoTestResult] = []

        pattern = r"---\s+(PASS|FAIL|SKIP):\s+(\S+)\s+\(([^)]+)\)"

        for match in re.finditer(pattern, logs):
            status, test_name, duration_str = match.groups()

            duration: float | None = None
            if duration_str:
                try:
                    duration = float(duration_str.rstrip("s"))
                except ValueError:
                    pass

            message = ""
            if status == "FAIL":
                # The failure body sits between `=== RUN` and the `--- FAIL:` line.
                run_pattern = rf"===\s+RUN\s+{re.escape(test_name)}\n(.*?)---\s+FAIL:\s+{re.escape(test_name)}"
                run_match = re.search(run_pattern, logs, re.DOTALL)
                if run_match:
                    test_output = run_match.group(1).strip()
                    if test_output:
                        message = test_output[:500] + ("..." if len(test_output) > 500 else "")
            elif status == "SKIP":
                skip_pattern = rf"{re.escape(test_name)}.*?:\s*(.+?)(?:\n|$)"
                skip_match = re.search(skip_pattern, logs)
                if skip_match:
                    message = skip_match.group(1).strip()

            results.append(
                GoTestResult(
                    name=test_name,
                    passed=status == "PASS",
                    skipped=status == "SKIP",
                    duration=duration,
                    message=message,
                )
            )

        return results

    def _report_results(self, logs: str, test_suite: str) -> None:
        """Parse and report test results from pod logs."""
        go_test_results = self._parse_go_test_results(logs)

        pass_count = sum(1 for r in go_test_results if r.passed)
        fail_count = sum(1 for r in go_test_results if not r.passed and not r.skipped)
        skip_count = sum(1 for r in go_test_results if r.skipped)

        passed_tests = [r.name for r in go_test_results if r.passed]
        failed_tests = [r.name for r in go_test_results if not r.passed and not r.skipped]
        skipped_tests = [r.name for r in go_test_results if r.skipped]

        # `panic:` from the Go runtime (e.g. timeout, nil deref) means at least
        # one test never reported a verdict — don't trust counts in that case.
        has_panic = "panic:" in logs

        log_lines = [line.strip() for line in logs.splitlines()]
        overall_passed = "PASS" in log_lines
        overall_failed = "FAIL" in log_lines

        results_details = [f"Results: {pass_count} passed, {fail_count} failed, {skip_count} skipped"]
        if has_panic:
            results_details.append("\nWARNING: Test panicked (likely timeout or runtime error)")
        if passed_tests:
            results_details.append("\nPassed tests:\n  - " + "\n  - ".join(passed_tests))
        if failed_tests:
            results_details.append("\nFailed tests:\n  - " + "\n  - ".join(failed_tests))
        if skipped_tests:
            results_details.append("\nSkipped tests:\n  - " + "\n  - ".join(skipped_tests))

        details_str = "\n".join(results_details)

        self.log.info("=" * 60)
        self.log.info("K8s Platform Validator - Full Test Output")
        self.log.info("=" * 60)
        for line in logs.split("\n"):
            self.log.info(line)
        self.log.info("=" * 60)

        # Only report top-level tests as subtests; reporting both parent and
        # children would double-count in the pytest summary.
        top_level_tests = [r for r in go_test_results if "/" not in r.name]

        if top_level_tests and self._subtests is not None:
            import sys

            for handler in self.log.handlers:
                handler.flush()
            sys.stdout.flush()
            sys.stderr.flush()

        for result in top_level_tests:
            self.report_subtest(
                name=result.name,
                passed=result.passed,
                message=result.message,
                skipped=result.skipped,
                duration=result.duration,
            )

        if top_level_tests and self._subtests is not None:
            print()

        self._output = logs

        # Priority: panic > explicit FAIL line > individual failures > overall PASS > individual passes
        if has_panic:
            self.set_failed(f"Platform validator ({test_suite}) PANICKED (timeout or runtime error)\n{details_str}")
        elif overall_failed:
            self.set_failed(f"Platform validator ({test_suite}) FAILED\n{details_str}")
        elif fail_count > 0:
            self.set_failed(f"Platform validator ({test_suite}) FAILED\n{details_str}")
        elif overall_passed:
            self.set_passed(f"Platform validator ({test_suite}) PASSED\n{details_str}")
        elif pass_count > 0 and fail_count == 0:
            self.log.warning("Tests passed but no overall PASS detected - possible incomplete run")
            self.set_passed(f"Platform validator ({test_suite}) PASSED (partial)\n{details_str}")
        else:
            self.log.warning("Could not parse test results from logs")
            if "ok" in logs.lower() and "fail" not in logs.lower():
                self.set_passed(f"Platform validator ({test_suite}) completed (results unclear)")
            else:
                self.set_failed(f"Platform validator ({test_suite}) status unclear\nPreview:\n{logs[:2000]}")


class K8sPlatformValidatorFunctional(K8sPlatformValidatorBase):
    """Convenience subclass: ``test_suite=functional``."""

    description = "K8s platform validation - functional Go tests"

    def __init__(self, runner: Runner | None = None, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        config.setdefault("test_suite", "functional")
        super().__init__(runner, config)


class K8sPlatformValidatorPerformance(K8sPlatformValidatorBase):
    """Convenience subclass: ``test_suite=performance`` with a 3 h default timeout."""

    description = "K8s platform validation - performance Go tests"
    timeout: ClassVar[int] = 10800  # 3 hours

    def __init__(self, runner: Runner | None = None, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        config.setdefault("test_suite", "performance")
        config.setdefault("timeout", 10800)
        super().__init__(runner, config)


class K8sPlatformValidatorNvstorage(K8sPlatformValidatorBase):
    """Convenience subclass: ``test_suite=nvstorage``.

    Mirrors the nvstorage suite in
    https://gitlab-master.nvidia.com/dgxcloud/mk8s/k8s-platform-validator
    (AWS FSx/S3, GCP Filestore/GCS-Fuse/Lustre, VAST, PVC lifecycle, storage
    webhook, nvdp-operator and scd-driver health). The Go test bodies live in
    the validator image; this class just selects them via ``TEST_SUITE``.
    """

    description = "K8s platform validation - nvstorage Go tests"

    def __init__(self, runner: Runner | None = None, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        config.setdefault("test_suite", "nvstorage")
        super().__init__(runner, config)
