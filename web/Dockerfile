# Build context: repo root  →  docker build -f web/Dockerfile -t mzpeak-validator-web .
FROM python:3.11-slim

WORKDIR /srv

# Install the validator package (pulls pyarrow, numpy)
COPY pyproject.toml ./
COPY mzpeak_validator/ ./mzpeak_validator/
RUN pip install --no-cache-dir .

# Install web service dependencies
COPY web/requirements.txt ./web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

COPY web/app.py ./web/app.py

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# ponytail: 1 worker keeps things simple; bump to --workers 2 under real load
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
