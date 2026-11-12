#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PUBLIC_PORT="${PUBLIC_PORT:-9000}"
PUBLIC_PATH="${PUBLIC_PATH:-}"

usage() {
  cat <<'EOF'
Usage: bash deploy/configure_public_proxy.sh [options]

Configures the Nginx public entrypoint without reinstalling the application.

Options:
  --public-port PORT   Nginx public HTTP port (default: 9000)
  --public-path PATH   Public URL suffix, for example fengyucai
  -h, --help           Show this help
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }
require_value() {
  [[ -n "${2:-}" && "${2:-}" != --* ]] || die "$1 requires a value"
}

while (($#)); do
  case "$1" in
    --public-port) require_value "$1" "${2:-}"; PUBLIC_PORT="$2"; shift 2 ;;
    --public-path) require_value "$1" "${2:-}"; PUBLIC_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ "${PUBLIC_PORT}" =~ ^[0-9]+$ ]] || die "--public-port must be numeric"
((PUBLIC_PORT >= 1 && PUBLIC_PORT <= 65535)) || die "Invalid public port"
PUBLIC_PATH="${PUBLIC_PATH#/}"
PUBLIC_PATH="${PUBLIC_PATH%/}"
[[ -z "${PUBLIC_PATH}" || "${PUBLIC_PATH}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || \
  die "Invalid public path; use lowercase letters, numbers, and hyphens"
[[ -s "${PROJECT_DIR}/frontend/dist/index.html" ]] || \
  die "Frontend build is missing; run bootstrap_server.sh first"
command -v nginx >/dev/null || die "Nginx is not installed"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

"${SUDO[@]}" tee /etc/nginx/sites-available/digital-human >/dev/null <<EOF
server {
    listen ${PUBLIC_PORT} default_server;
    listen [::]:${PUBLIC_PORT} default_server;
    server_name _;
    root ${PROJECT_DIR}/frontend/dist;
    index index.html;
    client_max_body_size 100m;

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location /avatar-api/ {
        rewrite ^/avatar-api/(.*)\$ /\$1 break;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

EOF

if [[ -n "${PUBLIC_PATH}" ]]; then
  "${SUDO[@]}" tee -a /etc/nginx/sites-available/digital-human >/dev/null <<EOF
    location = / {
        return 302 /${PUBLIC_PATH};
    }

    location = /${PUBLIC_PATH} {
        try_files /index.html =404;
    }

    location = /${PUBLIC_PATH}/ {
        return 301 /${PUBLIC_PATH};
    }

    location / {
        try_files \$uri \$uri/ =404;
    }
EOF
else
  "${SUDO[@]}" tee -a /etc/nginx/sites-available/digital-human >/dev/null <<'EOF'
    location / {
        try_files $uri $uri/ /index.html;
    }
EOF
fi

"${SUDO[@]}" tee -a /etc/nginx/sites-available/digital-human >/dev/null <<'EOF'
}
EOF

"${SUDO[@]}" rm -f /etc/nginx/sites-enabled/default
"${SUDO[@]}" ln -sfn /etc/nginx/sites-available/digital-human \
  /etc/nginx/sites-enabled/digital-human
"${SUDO[@]}" nginx -t
"${SUDO[@]}" systemctl reload-or-restart nginx

if [[ -n "${PUBLIC_PATH}" ]]; then
  echo "Nginx public path: /${PUBLIC_PATH}"
else
  echo "Nginx public path: /"
fi
