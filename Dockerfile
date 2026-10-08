# 워시타워 세탁기 A/S 상담 도우미 실행 이미지
#   빌드: docker build -t washer-consult .          (Railway 등 x86 서버용: --platform linux/amd64)
#   실행: docker run --rm -p 7860:7860 -e OPENAI_API_KEY=... washer-consult
# 기본 검색 방식(child_rerank_code)은 재정렬 모델 때문에 RAM 약 3GB가 필요합니다.
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    HF_HOME=/app/hf_cache

WORKDIR /app

# 실행 사용자와 쓰기 폴더를 먼저 만듭니다. 모델을 받은 뒤에 chown하면 2.2GB 레이어가 한 번 더 생깁니다.
RUN useradd --create-home appuser \
    && mkdir -p /app/qdrant_db /app/hf_cache \
    && chown appuser /app/qdrant_db /app/hf_cache

# torch는 CPU 전용 빌드를 먼저 설치합니다. 그냥 설치하면 GPU(CUDA) 라이브러리까지 받아 이미지가 수 GB 커집니다.
# 뒤의 sentence-transformers는 이미 설치된 torch를 그대로 씁니다.
RUN pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu

# 의존성 레이어를 먼저 만들어, 코드만 바뀌면 pip 설치를 다시 하지 않습니다.
COPY requirements.txt .
RUN pip install -r requirements.txt

# 여기부터 루트가 아닌 사용자로 실행합니다(시작할 때 Qdrant 색인을 /app/qdrant_db에 만듭니다).
USER appuser

# 재정렬 모델(약 2.2GB)을 빌드할 때 받아 둡니다. 실행 중에 받으면 재시작할 때마다 첫 질문이 수 분 걸립니다.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-v2-m3', allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt'])"
# 실행 중에는 모델을 내려받지 않습니다(이미지에 넣은 모델만 사용).
ENV HF_HUB_OFFLINE=1

# 상담에 필요한 파일만 넣습니다(평가 스크립트·결과·검수용 이미지·로컬 색인은 제외, .dockerignore 참고).
COPY app.py wachingmachine_service_manual.pdf ./
COPY data/pages ./data/pages
COPY assets ./assets

EXPOSE 7860
# app.py가 PORT 환경변수를 읽어 0.0.0.0에 바인딩합니다(Railway는 PORT를 주입).
CMD ["python", "app.py"]
