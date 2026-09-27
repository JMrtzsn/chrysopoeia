FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.8.13

WORKDIR /app
COPY ./pyproject.toml ./uv.lock ./chrysopoeia.toml ./
COPY ./chrysopoeia ./chrysopoeia

RUN uv sync --frozen --no-dev

# venue adapter and Vertex calls run over HTTPS; no egress broker required
ENTRYPOINT ["uv", "run", "--no-sync", "chrysopoeia"]
