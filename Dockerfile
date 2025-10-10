FROM python:3.12-slim
LABEL org.opencontainers.image.title="cognis-fhirlint"
LABEL org.opencontainers.image.source="https://github.com/cognis-digital/fhirlint"
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
ENTRYPOINT ["fhirlint"]
