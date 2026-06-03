FROM python:3.12.3-slim

RUN pip install newrelic flask ariadne gpiozero waitress flask-cors

RUN mkdir /app
WORKDIR /app

COPY ./sprinkler.py ./
COPY ./schema.graphql ./
COPY ./newrelic.ini ./
