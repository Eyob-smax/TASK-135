FROM python:3.10-slim

ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages required for PyQt6 (even in offscreen/test mode) and async I/O
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libgl1 \
    libegl1 \
    libfontconfig1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libglib2.0-0 \
    libdbus-1-3 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer-cached unless requirements change)
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
RUN python -m pip install --no-cache-dir "setuptools>=68" wheel

# Copy application source
COPY . .

# Install the district_console package in editable mode (src layout)
RUN python -m pip install --no-cache-dir -e .

# Use Qt offscreen platform for headless test environments
ENV QT_QPA_PLATFORM=offscreen
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Local REST service port
EXPOSE 8765

# Default entrypoint is overridden by docker-compose per service
CMD ["python", "-m", "district_console.bootstrap"]
