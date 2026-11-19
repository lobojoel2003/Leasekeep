# syntax=docker/dockerfile:1
# Leasekeep production image: gunicorn + WhiteNoise, runs as an unprivileged user.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /venv && /venv/bin/pip install --no-compile -r requirements.txt
COPY manage.py ./
COPY leasekeep ./leasekeep
RUN LEASEKEEP_ENV=production DJANGO_SECRET_KEY=collectstatic-only \
    /venv/bin/python manage.py collectstatic --noinput --verbosity 0

FROM python:${PYTHON_VERSION}-slim
ARG VERSION=dev
ARG BUILD_NUMBER=dev
ARG GIT_SHA=""
ARG BUILD_DATE=""
LABEL org.opencontainers.image.title="Leasekeep" \
      org.opencontainers.image.description="Stewardship software for community land trusts" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/lobojoel2003/Leasekeep" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"
ENV PATH="/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LEASEKEEP_ENV=production \
    LEASEKEEP_STATIC_ROOT=/app/staticfiles \
    LEASEKEEP_MEDIA_ROOT=/data/media \
    LEASEKEEP_BUILD_NUMBER=${BUILD_NUMBER} \
    LEASEKEEP_GIT_SHA=${GIT_SHA} \
    LEASEKEEP_BUILD_DATE=${BUILD_DATE} \
    PORT=8000
RUN groupadd --system --gid 1000 leasekeep \
 && useradd --system --uid 1000 --gid leasekeep --home-dir /app --shell /usr/sbin/nologin leasekeep \
 && mkdir -p /data/media && chown -R leasekeep:leasekeep /data
WORKDIR /app
COPY --from=build /venv /venv
COPY --from=build --chown=leasekeep:leasekeep /app /app
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/leasekeep-entrypoint
USER leasekeep
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"
ENTRYPOINT ["leasekeep-entrypoint"]
CMD ["web"]
