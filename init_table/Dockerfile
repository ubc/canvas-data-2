FROM python:3-alpine

USER app
WORKDIR /code

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
COPY . ./

ADD https://s3.amazonaws.com/rds-downloads/rds-combined-ca-bundle.pem .

CMD ["python", "app.py"]