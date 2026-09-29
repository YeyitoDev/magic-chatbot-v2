FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p images output logs csv estados credentials

# startup.py escribe las credenciales de Google desde GOOGLE_CREDENTIALS_JSON
# (fly secret) hacia credentials/google.json antes de arrancar el bot.
CMD python startup.py && python main.py
