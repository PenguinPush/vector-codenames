FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 GEMMA_CACHE_DIR=/app/.cache
COPY pyproject.toml README.md ./
COPY gemma_codenames ./gemma_codenames
RUN pip install '.[gemma,geometry]'
EXPOSE 8000
CMD ["codenames"]
