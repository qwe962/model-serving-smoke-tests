FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && mkdir /work \
    && chown 65532:65532 /work

WORKDIR /work
USER 65532:65532
ENTRYPOINT ["model-serving-smoke-tests"]
