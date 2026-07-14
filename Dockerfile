FROM python:3.14-slim AS problemtools

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY ./libs/problemtools /build

# Problemtools usually fetches its version string from git info, but this might not be present, hence just pretend to be 0.1
RUN (cd /build/libs/problemtools && make) \
  && SETUPTOOLS_SCM_PRETEND_VERSION="0.1" pip install --no-cache-dir /build

FROM python:3.14-slim AS builder
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY --from=problemtools /opt/venv /opt/venv

COPY . /build
RUN pip install --no-cache-dir /build

FROM python:3.14-slim
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv

RUN pip install gunicorn

COPY docker_entrypoint.sh /app
RUN chmod +x docker_entrypoint.sh
ENTRYPOINT ["/app/docker_entrypoint.sh"]