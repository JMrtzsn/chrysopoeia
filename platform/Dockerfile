FROM python:3.12-slim

# The harness is consumed as a wheel (built by harness/ `uv build`), never as
# source: platform never imports harness code, it installs the artifact. The
# harness's checked-in config file travels alongside it and is selected via
# CHRYSOPOEIA_CONFIG.
COPY .build/*.whl /tmp/harness/
COPY .build/chrysopoeia.toml /etc/chrysopoeia.toml
COPY .build/platform.toml /etc/chrysopoeia-platform.toml

RUN pip install --no-cache-dir /tmp/harness/*.whl \
  && rm -rf /tmp/harness

ENV CHRYSOPOEIA_CONFIG=/etc/chrysopoeia.toml

# venue adapter and Vertex calls run over HTTPS; no egress broker required
ENTRYPOINT ["chrysopoeia"]
