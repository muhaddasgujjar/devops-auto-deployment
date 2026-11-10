ARG PYTHON_IMAGE
ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend /frontend
RUN npm test && npm run build \
    && npm audit --omit=dev --audit-level=high --json > /frontend-audit.json

FROM ${PYTHON_IMAGE} AS dependencies
COPY wheelhouse /wheels
COPY requirements-backend-musl.lock /requirements.lock
RUN python -m pip install --no-cache-dir --no-index --require-hashes --find-links=/wheels -r /requirements.lock \
    && python -m pip check

FROM ${PYTHON_IMAGE} AS runtime
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=${SOURCE_SHA}
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend /app/backend
COPY --from=frontend /frontend/dist /app/frontend/dist
USER 10001:10001
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "backend.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]

FROM runtime AS test
COPY --from=frontend /frontend-audit.json /app/frontend-audit.json
COPY backend_tests /app/backend_tests
COPY scripts /app/scripts
COPY ci/backend_tests_entrypoint.py /app/ci/backend_tests_entrypoint.py
COPY docs /app/docs
COPY alembic.ini /app/alembic.ini
CMD ["python", "/app/ci/backend_tests_entrypoint.py"]
