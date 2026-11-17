FROM python:3.11-alpine

RUN pip install --no-cache-dir flask==3.0.3 gunicorn==22.0.0

WORKDIR /app

COPY app.py /app/app.py
COPY templates /app/templates

# static 目录由 volume 挂载（复用已有图片），这里留个占位避免启动报错
RUN mkdir -p /app/static

EXPOSE 8081

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8081", "--access-logfile", "-", "app:app"]
