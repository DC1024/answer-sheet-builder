# 纯静态前端 + Python 服务同镜像，依赖极小（numpy / opencv-headless / flask / waitress）
FROM python:3.12-slim

# 默认走清华源：内网/无梯子环境也能构建。海外或私有源用 --build-arg PIP_INDEX=... 覆盖。
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt

# 手写 A-D CNN（app/cnn_letter.py）所需的 PyTorch CPU 版，单独从官方 PyPI 装
# （tuna 镜像不保证同步 torch 这种大体量包）。缺失时 app 仍正常启动，
# decode_write 自动退回纯 OpenCV（_get_cnn_model 优雅降级）。
# 锁定 2.14.0 与训练环境一致，避免 state_dict 跨版本加载风险。
RUN pip install --no-cache-dir torch==2.14.0

COPY app ./app

EXPOSE 8081
VOLUME ["/srv/data"]

CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8081", "--call", "app.server:create_app"]
