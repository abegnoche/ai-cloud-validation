#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
