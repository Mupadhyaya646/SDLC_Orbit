FROM python:3.12-slim

# Set working directory to app root (not the app package folder)
WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Ensure /app is in PYTHONPATH for proper module resolution
ENV PYTHONPATH=/app:$PYTHONPATH

EXPOSE 6001

# Run the server. NOTE: app/server.py MUST bind to 0.0.0.0:6001,
# not 127.0.0.1, or the kubelet probe will get "connection refused".
CMD ["python", "-m", "app.server"]
