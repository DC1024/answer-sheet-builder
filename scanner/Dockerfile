# 纯静态前端 + Python 服务同镜像，依赖极小（numpy / opencv-headless / flask / waitress）
FROM python:3.12-slim

# 默认走清华源：内网/无梯子环境也能构建。海外或私有源用 --build-arg PIP_INDEX=... 覆盖。
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt

# 手写 A-D CNN（app/cnn_letter.py）所需的 PyTorch CPU 版。三个坑：
#  1) slim 基础镜像不含 libgomp1，而 torch CPU 轮子链接它 —— 缺了 import torch 直接失败，
#     CNN 会静默退回纯 OpenCV（_get_cnn_model 优雅降级）。必须先装 libgomp1。
#  2) **必须用 CPU 专用索引** `download.pytorch.org/whl/cpu`：PyPI/tuna 上的 `torch` 是
#     CUDA 构建，会拖进 ~3GB 的 nvidia-* / cuda-* / triton 依赖（镜像暴涨，还撑爆磁盘）。
#  3) 锁 2.14.0 与训练环境一致，避免 state_dict 跨版本加载风险。
# torch 的运行依赖（filelock/sympy/…）走 PIP_INDEX，避免 CPU 索引缺依赖。
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 \
    && pip install --no-cache-dir -i ${PIP_INDEX} filelock typing-extensions sympy networkx jinja2 fsspec

COPY app ./app

EXPOSE 8081
VOLUME ["/srv/data"]

CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8081", "--call", "app.server:create_app"]
