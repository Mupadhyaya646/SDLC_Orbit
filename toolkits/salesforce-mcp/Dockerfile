FROM python:3.12-slim

# Set working directory to app root (not the app package folder)
WORKDIR /app

# sf CLI (Salesforce CLI) is required by sf_deploy_validate (app/salesforce/
# deploy_validate.py) — Node.js is needed to install/run it. Node 20.x +
# latest @salesforce/cli crashed on login with "TypeError:
# webidl.util.markAsUncloneable is not a function" inside undici's
# CacheStorage (confirmed live against this exact image). Root cause,
# confirmed via `npm view @salesforce/cli engines`: @salesforce/cli
# requires Node >=22.0.0 -- this Dockerfile was installing Node 20.x.
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @salesforce/cli \
    && apt-get purge -y curl gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && sf --version

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Ensure /app is in PYTHONPATH for proper module resolution
ENV PYTHONPATH=/app:$PYTHONPATH

EXPOSE 6000

# Run the server. NOTE: app/server.py MUST bind to 0.0.0.0:6000 (matches
# deploy-salesforce-mcp.yaml's containerPort/PORT env var), not 127.0.0.1,
# or the kubelet probe will get "connection refused".
CMD ["python", "-m", "app.server"]
