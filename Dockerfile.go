# Build only after selecting digest-pinned base images; never built automatically.
ARG GO_IMAGE
ARG EVALUATOR_IMAGE
FROM ${GO_IMAGE} AS go
FROM ${EVALUATOR_IMAGE}
ARG BENCH_SHA
RUN test -n "$BENCH_SHA"
LABEL com.sanka.bench.revision=$BENCH_SHA
USER root
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap strace \
    && rm -rf /var/lib/apt/lists/*
COPY --from=go /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}" \
    GOTOOLCHAIN=local GOWORK=off GOPROXY=off GOMODCACHE=/opt/go-mod-cache
COPY toolchains/python-go/ /opt/go-lock/
COPY scripts/check_go_module_cache.sh /opt/go-lock/check-cache.sh
RUN cd /opt/go-lock && GOPROXY=https://proxy.golang.org go mod download all \
    && go mod edit -require="$(go list -m -f '{{.Path}}@{{.Version}}' github.com/stretchr/testify)" \
    && GOPROXY=https://proxy.golang.org go mod download all \
    && go mod verify && GOPROXY=off go list -m all >/dev/null \
    && sh /opt/go-lock/check-cache.sh /opt/go-lock && chmod -R a+rX /opt/go-mod-cache
COPY src /bench/src
COPY tasks /bench/tasks
COPY baselines /bench/baselines
