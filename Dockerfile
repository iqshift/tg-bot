# ═══════════════════════════════════════════════════
# Dockerfile - مشروع SHΔDØW BOT
# متوافق مع Google Cloud Run
# ═══════════════════════════════════════════════════

FROM python:3.11-slim

# تثبيت ffmpeg لمعالجة الفيديو
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# مجلد العمل
WORKDIR /app

# تثبيت المتطلبات أولاً (للاستفادة من Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كود المشروع
COPY . .

# إنشاء المجلدات الضرورية
RUN mkdir -p downloads logs data/cookies

# المنفذ (Cloud Run يستخدم 8080 افتراضياً)
EXPOSE 8080

# تشغيل البوت
CMD ["python", "main.py"]
