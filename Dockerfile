FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 8799
CMD ["hermes-usage-sidecar", "--hermes-home", "/hermes", "--state-db", "/state/state.db", "--bind", "0.0.0.0", "--port", "8799"]
