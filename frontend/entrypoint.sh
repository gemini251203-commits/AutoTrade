#!/bin/sh
# ==========================================
# AutoTrade Frontend Entrypoint
# ==========================================
# Dynamically generate .htpasswd from environment variables
# so credentials survive git pull / docker rebuild.
#
# Required env vars:
#   WEB_ACCESS_USERNAME  (default: admin)
#   WEB_ACCESS_PASSWORD  (default: AutoTrade2026)

HTPASSWD_FILE="/etc/nginx/conf.d/.htpasswd"

if [ -n "$WEB_ACCESS_USERNAME" ] && [ -n "$WEB_ACCESS_PASSWORD" ]; then
    # Generate .htpasswd using openssl (available in nginx:alpine)
    HASH=$(openssl passwd -apr1 "$WEB_ACCESS_PASSWORD")
    echo "${WEB_ACCESS_USERNAME}:${HASH}" > "$HTPASSWD_FILE"
    echo "[entrypoint] Generated .htpasswd for user: $WEB_ACCESS_USERNAME"
else
    echo "[entrypoint] WARNING: WEB_ACCESS_USERNAME/PASSWORD not set, using bundled .htpasswd"
fi

# Start Nginx
exec nginx -g 'daemon off;'
