FROM frikky/shuffle:app_sdk

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ .
CMD ["python", "app.py", "--port", "5001"]
