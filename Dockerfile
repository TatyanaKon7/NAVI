FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot bot
COPY config config
COPY manage.py .
COPY data data
RUN python manage.py collectstatic --noinput
CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--trusted-proxy=*", "--trusted-proxy-headers=x-forwarded-proto", "config.wsgi:application"]
