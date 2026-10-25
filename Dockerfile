# Image for the web tools (self-service registration and fuzzer), see docs/tools.md.

FROM python:3.13-slim AS problemtools

# checktestdata needs the GMP C++ bindings and the (header-only) Boost parts
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential automake libboost-dev libgmp-dev make \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY ./libs/problemtools /build

# problemtools takes its version from git (setuptools-scm), but the submodule's
# git metadata is not part of the build context, so pretend a version instead
RUN make \
  && SETUPTOOLS_SCM_PRETEND_VERSION="0.1" pip install --no-cache-dir /build

FROM python:3.13-slim AS builder
ENV PATH="/opt/venv/bin:$PATH"
COPY --from=problemtools /opt/venv /opt/venv

COPY . /build
RUN pip install --no-cache-dir /build gunicorn

FROM python:3.13-slim
# Runtime for checktestdata (GMP) and for judging Python submissions, which
# problemtools runs with /usr/bin/pypy3. Fuzzing submissions in other languages
# needs an image extended with their compilers (g++, a JDK, ...).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp10 libgmpxx4ldbl pypy3 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv

COPY docker_entrypoint.sh /app
RUN chmod +x docker_entrypoint.sh
ENTRYPOINT ["/app/docker_entrypoint.sh"]
