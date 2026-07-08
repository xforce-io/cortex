FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY cortex /app/cortex
COPY web /app/web
RUN pip install --no-cache-dir -e .

ENV CORTEX_HOME=/var/lib/cortex
EXPOSE 8000
CMD ["python", "-m", "cortex.api"]
