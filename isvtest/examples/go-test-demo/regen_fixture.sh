#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# Rebuild the tiny Go-test demo and refresh the Python parser's fixture.
# Run this if you change demo_test.go.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Script lives at isvtest/examples/go-test-demo/, fixture at isvtest/tests/fixtures/.
fixture="$(cd "$script_dir/../../tests/fixtures" && pwd)/go_test_demo_output.txt"

cd "$script_dir"
go test -c -o demo.test .
# TestDemoFail makes the binary exit non-zero by design; that's expected.
./demo.test -test.v > "$fixture" || true
rm -f demo.test

echo "Regenerated: $fixture"
