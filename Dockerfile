FROM python:3.12-slim

WORKDIR /app

# نصب وابستگی‌ها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کد
COPY . .

# اجرای ربات
CMD ["python", "-u", "bot.py"]
