FROM python:3.12-slim

COPY dist/*.whl /tmp/
COPY .build/trade_plan_ready.v1.schema.json /opt/contracts/trade_plan_ready.v1.schema.json
COPY .build/trade_plan_ready.v2.schema.json /opt/contracts/trade_plan_ready.v2.schema.json
COPY .build/consumer_outcome.v1.schema.json /opt/contracts/consumer_outcome.v1.schema.json
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

ENV TRADE_PLAN_SCHEMA=/opt/contracts/trade_plan_ready.v1.schema.json
ENV CONSUMER_OUTCOME_SCHEMA=/opt/contracts/consumer_outcome.v1.schema.json
CMD ["uvicorn", "paper_consumer.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
