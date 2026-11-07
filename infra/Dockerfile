# One image for both jobs, built from the repo root:
#   docker build -f infra/Dockerfile .
# On Lambda, the web adapter starts first and passes each web request to the review
# page, which the default command starts. On Fargate, the task gives the command
# `night-run` instead, and the web adapter is not used.
FROM public.ecr.aws/docker/library/python:3.13-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The libraries first, so a change to the code does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra aws --extra langfuse --extra jev

COPY src ./src
COPY examples ./examples
RUN uv sync --frozen --no-dev --extra aws --extra langfuse --extra jev

# The web adapter sends requests to this port, and the default command listens on it.
ENV AWS_LWA_PORT=8080 \
    WHY_NOW_DEPLOYMENT=aws

ENTRYPOINT ["why-now"]
CMD ["serve", "--port", "8080"]
