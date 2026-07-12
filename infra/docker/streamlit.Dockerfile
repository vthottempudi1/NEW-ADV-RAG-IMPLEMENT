# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.streamlit.txt ./requirements.streamlit.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.streamlit.txt

COPY ui/streamlit/app.py ./ui/streamlit/app.py

EXPOSE 8501

CMD ["streamlit", "run", "ui/streamlit/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
