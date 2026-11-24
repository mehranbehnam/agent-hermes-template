# Agent Hermes per-user sandbox (Rule #1: one sealed container per user profile; only that user's folders are mounted).
# Python + Telethon come from the host's /root/.hermes/tools (mounted read-only), so this image stays small.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash coreutils findutils grep sed gawk ripgrep curl ca-certificates procps file less unzip zip jq tzdata locales \
      poppler-utils tesseract-ocr tesseract-ocr-fas ffmpeg \
    && sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
    && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 TZ=Asia/Tehran PYTHONIOENCODING=utf-8
CMD ["sleep", "infinity"]
