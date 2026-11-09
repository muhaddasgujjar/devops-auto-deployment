FROM python:3.14-alpine3.24@sha256:a18b20ad69e74df6cf6d2e1b1a260d7a1ecf5380fd83b310f83ba88c461cf894
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
