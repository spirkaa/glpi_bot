FROM python:3.7

WORKDIR /app

COPY requirements.txt .

RUN set -eux \
    && pip install --no-cache-dir -U -r requirements.txt

COPY glpi_bot .

CMD ["python", "bot.py"]
