# 워시타워 세탁기 A/S 상담 도우미 실행 이미지
#   빌드: docker build -t washer-consult .
#   실행: docker run --rm -p 7860:7860 -e OPENAI_API_KEY=... washer-consult
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

WORKDIR /app

# 의존성 레이어를 먼저 만들어, 코드만 바뀌면 pip 설치를 다시 하지 않습니다.
COPY requirements.txt .
RUN pip install -r requirements.txt

# 상담에 필요한 파일만 넣습니다(평가 스크립트·결과는 제외, .dockerignore 참고).
COPY app.py wachingmachine_service_manual.pdf ./
COPY assets ./assets

# 루트가 아닌 사용자로 실행합니다.
RUN useradd --create-home appuser
USER appuser

EXPOSE 7860
# app.py가 PORT 환경변수를 읽어 0.0.0.0에 바인딩합니다(Render는 PORT를 주입).
CMD ["python", "app.py"]
