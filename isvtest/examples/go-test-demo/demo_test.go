// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: LicenseRef-NvidiaProprietary
//
// Package demo is a tiny Go test binary used to exercise
// K8sPlatformValidatorBase's output parser end-to-end without depending on
// the internal nvcr.io/nv-ngc-devops/k8s-platform-validator image.
//
// Build the test binary (no main needed for `go test -c`):
//
//	go test -c -o demo.test .
//
// Run it directly:
//
//	./demo.test -test.v
//
// Or via Docker, with the same entrypoint pattern as the upstream validator:
//
//	docker build -t go-test-demo:latest .
//	docker run --rm go-test-demo:latest -test.v
//
// The binary emits one passing, one failing, and one skipped top-level test,
// plus a couple of subtests, so every status the parser handles is present
// in the output. Exit code is non-zero because of TestDemoFail — that's by
// design (a real Go test binary exits non-zero when any test fails).
package demo

import (
	"testing"
	"time"
)

func TestDemoPass(t *testing.T) {
	time.Sleep(10 * time.Millisecond)
	if 1+1 != 2 {
		t.Fatal("math is broken")
	}
}

func TestDemoFail(t *testing.T) {
	t.Errorf("intentional failure: expected %d, got %d", 42, 41)
}

func TestDemoSkip(t *testing.T) {
	t.Skip("intentional skip: this scenario isn't applicable in the demo")
}

func TestDemoSubtests(t *testing.T) {
	t.Run("subtest_one", func(t *testing.T) {
		time.Sleep(5 * time.Millisecond)
	})
	t.Run("subtest_two", func(t *testing.T) {
		time.Sleep(5 * time.Millisecond)
	})
}
