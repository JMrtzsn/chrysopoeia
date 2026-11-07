FROM python:3.12-slim

COPY .build/requirements.txt /tmp/observer/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/observer/requirements.txt

COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm /tmp/*.whl

CMD ["uvicorn", "observer.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
