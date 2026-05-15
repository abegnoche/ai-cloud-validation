# Go test demo for `K8sPlatformValidatorBase`

<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: LicenseRef-NvidiaProprietary
-->

A tiny, self-contained Go test binary used to prove that
`K8sPlatformValidatorBase` (in `isvtest/src/isvtest/workloads/k8s_platform_validator.py`)
correctly:

1. submits a Kubernetes Job whose container runs a Go test binary,
2. tails its stdout, and
3. reports each top-level Go test as a pytest subtest.

It's the open-source-friendly stand-in for the internal
`nvcr.io/nv-ngc-devops/k8s-platform-validator` image used inside NVIDIA.

## What it tests

`demo_test.go` deliberately emits one of each verdict so every code path in
the parser is exercised:

- `TestDemoPass`     — passes
- `TestDemoFail`     — fails (with `t.Errorf`, so the binary exits non-zero)
- `TestDemoSkip`     — skipped via `t.Skip`
- `TestDemoSubtests` — top-level pass containing two `t.Run` subtests

## Run it locally

```bash
cd isvtest/examples/go-test-demo
go test -c -o demo.test .
./demo.test -test.v
```

You'll see standard Go test output (`=== RUN`, `--- PASS:`, `--- FAIL:`,
`--- SKIP:`). The binary exits non-zero because of the intentional
`TestDemoFail` — that's correct behavior.

## Run it as a container

```bash
docker build -t go-test-demo:latest isvtest/examples/go-test-demo
docker run --rm go-test-demo:latest -test.v
```

The Dockerfile mirrors the entrypoint contract the real validator image uses:
the test binary is the entrypoint, so anything you pass after the image name
goes straight to `-test.run`, `-test.skip`, etc.

## Use it as the `image` for `K8sPlatformValidatorBase`

Push the image to a registry your cluster can pull from, then point a config
at it:

```yaml
- K8sPlatformValidatorBase:
    image: registry.example.com/go-test-demo:latest
    cloud_provider: aws
    test_suite: functional
    skip_infrastructure_check: true
```

The workload will submit a Job with that image, tail the pod logs, and report
`TestDemoPass`, `TestDemoFail`, `TestDemoSkip`, and `TestDemoSubtests` as
pytest subtests in the run output and JUnit XML.

## Regenerate the parser fixture

`isvtest/tests/fixtures/go_test_demo_output.txt` is a captured copy of
`./demo.test -test.v`'s output. The Python test
`TestRealGoOutputFixture` pipes that fixture through the parser to prove it
handles real `go test` output (not just hand-written strings). If you change
`demo_test.go`, regenerate the fixture:

```bash
isvtest/examples/go-test-demo/regen_fixture.sh
```

You need `go` on your PATH (any version that can compile the source —
1.21 or newer). CI does **not** need Go installed: it just reads the
checked-in fixture.
