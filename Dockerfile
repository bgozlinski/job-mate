FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y

COPY pyproject.toml uv.lock ./
RUN pip install uv

RUN uv sync --frozen --no-install-project
#RUN poetry config virtualenvs.create false && poetry install --no-root

COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]