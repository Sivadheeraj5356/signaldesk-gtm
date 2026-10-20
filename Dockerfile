FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
COPY server.py storage.py security.py research.py jobs.py backup.py index.html login.html supabase-ca.crt ./
RUN mkdir /data && chown app:app /data
USER app
ENV SIGNALDESK_MODE=server SIGNALDESK_DB=/data/signaldesk.sqlite3 PORT=8787 PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python","server.py"]
