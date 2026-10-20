FROM python:3.14.8-alpine3.24@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72
# The demo uses only the standard library; do not ship unused Python build tools.
RUN python -m pip uninstall -y pip setuptools wheel
ARG DEMO_MODE=healthy
ARG APP_REVISION=local
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEMO_MODE=${DEMO_MODE} APP_REVISION=${APP_REVISION}
WORKDIR /app
COPY --chown=10001:10001 demo /app/demo
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["python", "-m", "demo.app"]
