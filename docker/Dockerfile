FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    httpx==0.27.2 \
    fastapi==0.115.0 \
    "uvicorn[standard]==0.30.6"

COPY extraflame_totalcontrol/ /app/extraflame_totalcontrol/
COPY docker/app.py /app/app.py

EXPOSE 8080
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
