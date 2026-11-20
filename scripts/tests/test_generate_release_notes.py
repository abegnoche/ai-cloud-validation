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

"""Tests for generate_release_notes.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "generate_release_notes", Path(__file__).resolve().parent.parent / "generate_release_notes.py"
)
assert _spec and _spec.loader
generate_release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_release_notes)


def _pr(number: int, title: str) -> generate_release_notes.IssueInfo:
    return generate_release_notes.IssueInfo(
        number=number, title=title, url=f"https://example.com/pull/{number}", is_pr=True, labels=[]
    )


@pytest.mark.parametrize(
    "title",
    [
        "chore: update package versions to 0.13.0",
        "chore: 1.1.0 release",
        "chore: 1.2.0-rc1 release",
    ],
)
def test_release_prs_are_skipped(title: str) -> None:
    milestone = generate_release_notes.MilestoneInfo(org="o", repo="r", milestone_number=1, title="M1")
    kept = _pr(1, "feat(k8s): add a check")

    markdown = generate_release_notes.generate_markdown(milestone, [kept, _pr(2, title)])

    assert "#1" in markdown
    assert "#2" not in markdown


@pytest.mark.parametrize("title", ["chore: release tooling cleanup", "chore(release): document tagging"])
def test_other_release_chores_are_kept(title: str) -> None:
    milestone = generate_release_notes.MilestoneInfo(org="o", repo="r", milestone_number=1, title="M1")

    markdown = generate_release_notes.generate_markdown(milestone, [_pr(3, title)])

    assert "#3" in markdown
