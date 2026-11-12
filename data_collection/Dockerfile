FROM python:3.12-slim
WORKDIR /collector
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY collector.py .
ENTRYPOINT ["python", "collector.py"]
