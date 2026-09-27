# 纯静态前端 + Python 服务同镜像，依赖极小（numpy / opencv-headless / flask / waitress）
FROM python:3.12-slim

# 默认走清华源：内网/无梯子环境也能构建。海外或私有源用 --build-arg PIP_INDEX=... 覆盖。
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt

# 手写 A-D CNN（app/cnn_letter.py）用 ONNX Runtime 推理：体积小、冷启快、不需要 libtorch。
# 权重 hwletter_cnn.onnx 已随 app/ 打进镜像；onnxruntime 在 requirements.txt 里装好。
# slim 基础镜像不含 libgomp1，而 onnxruntime 的 CPU EP 链接它 —— 缺了 import 会直接失败、
# CNN 静默退回纯 OpenCV（_get_cnn_model 优雅降级），所以必须先装。
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app

EXPOSE 8081
VOLUME ["/srv/data"]

CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8081", "--call", "app.server:create_app"]
