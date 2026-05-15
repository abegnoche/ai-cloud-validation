# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# Tiny Go-test container that mirrors the entrypoint contract used by
# k8s-platform-validator: the entrypoint forwards CLI args to the test
# binary (e.g. -test.run, -test.skip), so K8sPlatformValidatorBase can
# point at this image to verify the end-to-end workflow without needing
# access to the internal NVIDIA validator image.
#
# Build:   docker build -t go-test-demo:latest isvtest/examples/go-test-demo
# Run:     docker run --rm go-test-demo:latest -test.v

FROM golang:1.26-alpine AS builder
WORKDIR /build
COPY go.mod ./
COPY demo_test.go ./
RUN go test -c -o /build/demo.test .

FROM alpine:3.23
COPY --from=builder /build/demo.test /app/demo.test
WORKDIR /app
ENTRYPOINT ["/app/demo.test"]
CMD ["-test.v"]
