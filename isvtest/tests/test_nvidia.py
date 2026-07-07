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

"""Tests for NVIDIA parsing helpers."""

from isvtest.core.nvidia import count_gpus_from_full_output, count_gpus_from_list_output, parse_cuda_version

_T4_SINGLE_GPU = """\
+---------------------------------------------------------------------------------------+
| NVIDIA-SMI 535.104.05             Driver Version: 535.104.05   CUDA Version: 12.2     |
|=========================================+======================+======================|
|   0  Tesla T4                       Off | 00000000:00:04.0 Off |                    0 |
| N/A   34C    P8               9W /  70W |      0MiB / 15360MiB |      0%      Default |
+-----------------------------------------+----------------------+----------------------+
"""

_A100_TWO_GPU_WITH_PROCESSES = """\
+---------------------------------------------------------------------------------------+
| NVIDIA-SMI 550.54.15              Driver Version: 550.54.15    CUDA Version: 12.4     |
|=========================================+========================+======================|
|   0  NVIDIA A100-SXM4-80GB          On  |   00000000:07:00.0 Off |                    0 |
| N/A   30C    P0              63W / 400W |      0MiB /  81920MiB   |      0%      Default |
+-----------------------------------------+------------------------+----------------------+
|   1  NVIDIA A100-SXM4-80GB          On  |   00000000:0A:00.0 Off |                    0 |
| N/A   29C    P0              62W / 400W |      0MiB /  81920MiB   |      0%      Default |
+-----------------------------------------+------------------------+----------------------+
| Processes:                                                                            |
|=======================================================================================|
|    0   N/A  N/A      1234      C   /usr/bin/python                             456MiB |
|    1   N/A  N/A      5678      C   /usr/bin/python                             789MiB |
+---------------------------------------------------------------------------------------+
"""

_GB200_FOUR_GPU = """\
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.58.03              Driver Version: 595.58.03      CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GB200                   On  |   00000008:01:00.0 Off |                    0 |
| N/A   38C    P0            181W / 1200W |       2MiB / 189471MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   1  NVIDIA GB200                   On  |   00000009:01:00.0 Off |                    0 |
| N/A   37C    P0            169W / 1200W |       4MiB / 189471MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   2  NVIDIA GB200                   On  |   00000018:01:00.0 Off |                    0 |
| N/A   37C    P0            158W / 1200W |       4MiB / 189471MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   3  NVIDIA GB200                   On  |   00000019:01:00.0 Off |                    0 |
| N/A   36C    P0            169W / 1200W |       0MiB / 189471MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
"""

class TestCountGpusFromListOutput:
    """Tests for count_gpus_from_list_output()."""

    def test_single_gpu(self) -> None:
        output = "GPU 0: NVIDIA GB200 (UUID: GPU-abc123)\n"
        assert count_gpus_from_list_output(output) == 1

    def test_multiple_gpus(self) -> None:
        output = (
            "GPU 0: NVIDIA A100-SXM4-80GB (UUID: GPU-aaa)\n"
            "GPU 1: NVIDIA A100-SXM4-80GB (UUID: GPU-bbb)\n"
        )
        assert count_gpus_from_list_output(output) == 2

    def test_no_gpus(self) -> None:
        assert count_gpus_from_list_output("No devices were found") == 0


class TestCountGpusFromFullOutput:
    """Tests for count_gpus_from_full_output()."""

    def test_single_non_nvidia_named_gpu(self) -> None:
        # "Tesla T4" has no "NVIDIA" prefix; it must still be counted.
        assert count_gpus_from_full_output(_T4_SINGLE_GPU) == 1

    def test_does_not_overcount_process_rows(self) -> None:
        # Process-table rows also start with a GPU index but have no Bus-Id
        # and must not be counted as additional GPUs.
        assert count_gpus_from_full_output(_A100_TWO_GPU_WITH_PROCESSES) == 2

    def test_gb200_four_gpu_node(self) -> None:
        # Newer nvidia-smi table layout (driver 595+) with multi-line GPU rows.
        assert count_gpus_from_full_output(_GB200_FOUR_GPU) == 4

    def test_no_gpus(self) -> None:
        assert count_gpus_from_full_output("No devices were found") == 0


class TestParseCudaVersion:
    """Tests for parse_cuda_version()."""

    def test_legacy_cuda_version_header(self) -> None:
        header = "| NVIDIA-SMI 550.54.15    Driver Version: 550.54.15    CUDA Version: 12.4     |"
        assert parse_cuda_version(header) == "12.4"

    def test_cuda_umd_version_header(self) -> None:
        header = "| NVIDIA-SMI 610.47    KMD Version: 610.47    CUDA UMD Version: 13.3     |"
        assert parse_cuda_version(header) == "13.3"

    def test_prefers_first_match_when_both_present(self) -> None:
        output = "CUDA Version: 12.4\nCUDA UMD Version: 13.3"
        assert parse_cuda_version(output) == "12.4"

    def test_returns_none_when_missing(self) -> None:
        assert parse_cuda_version("Driver Version: 550.54.15") is None
