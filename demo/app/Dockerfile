# Supply a resolved official Python image digest using --build-arg PYTHON_IMAGE=...
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8080
WORKDIR /app
COPY --chown=10001:10001 server.py /app/server.py
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["python", "/app/server.py"]
