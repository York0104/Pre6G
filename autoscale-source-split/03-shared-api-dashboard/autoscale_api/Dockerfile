FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /opt/pre6g

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY autoscale-source-split/03-shared-api-dashboard/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /tmp/requirements.txt

COPY autoscale-source-split/01-monitoring-layer /opt/pre6g/autoscale-source-split/01-monitoring-layer
COPY autoscale-source-split/03-shared-api-dashboard /opt/pre6g/autoscale-source-split/03-shared-api-dashboard

WORKDIR /opt/pre6g/autoscale-source-split/03-shared-api-dashboard/autoscale_api

ENV PYTHONPATH=/opt/pre6g/autoscale-source-split/03-shared-api-dashboard/autoscale_api:/opt/pre6g/autoscale-source-split/01-monitoring-layer

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
