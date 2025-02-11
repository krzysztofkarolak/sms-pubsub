FROM python:3-alpine

RUN apk add --no-cache \
    build-base \
    gcc \
    g++ \
    libffi-dev \
    musl-dev \
    openssl-dev \
    python3-dev \
    git \ 
    make \
    musl-dev \
    go

ENV GOROOT /usr/lib/go
ENV GOPATH /go
ENV PATH /go/bin:$PATH
RUN mkdir -p ${GOPATH}/src ${GOPATH}/bin

RUN go install github.com/kenshaw/hilink/cmd/hlcli@latest

WORKDIR /service
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . ./
ENTRYPOINT ["python3", "sms.py"]