FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
ENV PYTHONPATH=/app/src
ENV OAB_PORT=8008
ENV OAB_MODE=live
EXPOSE 8008
# /health is a REAL self-check (providers configured for this MODE); it does NOT call the LLM.
HEALTHCHECK --interval=30s --timeout=4s --start-period=5s \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:8008/health'); sys.exit(0 if r.status==200 else 1)"
CMD ["sh","-c","uvicorn oab.api:app --host 0.0.0.0 --port ${OAB_PORT}"]
