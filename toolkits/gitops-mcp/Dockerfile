FROM python:3.12-slim

# Set working directory to app root (not the app package folder)
WORKDIR /app

# This server shells out to git, the GitHub CLI (gh), and the Salesforce
# CLI (sf) — all three are genuinely required, not optional:
#   - git:  every tool operates on a persistent clone (base.py)
#   - gh:   gh_create_pr
#   - sf:   sf_list_orgs / sf_deploy_validate (Gate 5)
# sf CLI install pattern copied from the sibling salesforce-mcp toolkit's
# Dockerfile for consistency (Node.js + npm install -g @salesforce/cli).
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @salesforce/cli \
    && (type -p wget >/dev/null || apt-get install -y --no-install-recommends wget) \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && wget -nv -O /etc/apt/keyrings/githubcli-archive-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && apt-get purge -y curl gnupg wget \
    && rm -rf /var/lib/apt/lists/* \
    && git --version && gh --version && sf --version

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Ensure /app is in PYTHONPATH for proper module resolution
ENV PYTHONPATH=/app:$PYTHONPATH

# Mount point for the persistent clone — see README.md for the matching
# PersistentVolumeClaim deploy-gitops-mcp.yaml needs added (not added by
# this change; this Dockerfile only needs the directory to exist so a
# volume can be mounted here).
RUN mkdir -p /data/repo
ENV REPO_CLONE_PATH=/data/repo

EXPOSE 6002

# Run the server. NOTE: app/server.py MUST bind to 0.0.0.0:6002 (matches
# deploy-gitops-mcp.yaml's containerPort/PORT env var), not 127.0.0.1, or
# the kubelet probe will get "connection refused".
CMD ["python", "-m", "app.server"]
