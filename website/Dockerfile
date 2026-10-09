# openwhistle.net (docs-tech/specs/2026-10-09-website-p4-design.md). Build: docker build -f website/Dockerfile .
# The site is built once on the build platform; the per-architecture stage only copies files.
FROM --platform=$BUILDPLATFORM python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2 AS site
COPY --from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/uv
# git: the sitemap's lastmod is each source's last commit (scripts/build_site.py lastmod()).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --only-group site --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt
COPY . .
RUN git config --global --add safe.directory /src \
    && python scripts/build_site.py --out /out/site \
    && python scripts/package_site.py /out/site /out/redirects.map

FROM docker.io/nginxinc/nginx-unprivileged:alpine@sha256:b9241c6e7b8e9a862f129d8d4199ab64b10390949a78bdd5603379b32c844083
USER root
RUN rm -f /etc/nginx/conf.d/default.conf && rm -rf /usr/share/nginx/html/*
COPY website/nginx.conf /etc/nginx/nginx.conf
COPY --from=site /out/redirects.map /etc/nginx/redirects.map
COPY --from=site /out/site /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html /etc/nginx
USER 101
EXPOSE 8080
# No entrypoint scripts: their stdout would mix into the counter log.
ENTRYPOINT ["nginx", "-g", "daemon off;"]
CMD []
