# 纯静态前端 + Python 服务同镜像，依赖极小（numpy / opencv-headless / flask / waitress）
FROM python:3.12-slim

# 默认走清华源：内网/无梯子环境也能构建。海外或私有源用 --build-arg PIP_INDEX=... 覆盖。
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt

COPY app ./app

EXPOSE 8081
VOLUME ["/srv/data"]

CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8081", "--call", "app.server:create_app"]
