FROM docker.io/library/python:3-alpine

ARG UID=1012
ARG GID=1012

RUN addgroup -S -g $GID cd2task
RUN adduser  -S -g $GID -u $UID -h /code cd2task

WORKDIR /code

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . ./

ADD https://s3.amazonaws.com/rds-downloads/rds-combined-ca-bundle.pem .

USER $UID

CMD ["python", "app.py"]