FROM python:3-alpine

RUN apk add --no-cache \
    build-base \
    gcc \
    g++ \
    libffi-dev \
    musl-dev \
    openssl-dev \
    python3-dev

WORKDIR /service
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . ./
ENTRYPOINT ["python3", "sms.py"]