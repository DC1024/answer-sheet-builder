#!/usr/bin/env bash
# 在 Ubuntu 服务器(192.168.43.18)上运行：从 GHCR 拉取最新 scanner 镜像并重建 asb-scan 容器。
# 走「GitHub push -> GHCR 镜像 -> Ubuntu 部署」管线，不再本机处理。
#
# 用法（服务器上）:
#   sudo bash tools/deploy_from_ghcr.sh [IMAGE_TAG]
# 默认 IMAGE_TAG=latest ；也可以传 sha-<commit> 精确定位。
set -euo pipefail

IMAGE="ghcr.io/dc1024/answer-sheet-builder-scanner:${1:-latest}"
SCAN_DIR="/opt/answer-sheet-scanner"
CONTAINER="asb-scan"
PORT=8081

echo "==> [1/4] 拉取镜像 ${IMAGE}"
docker pull "${IMAGE}"

echo "==> [2/4] 备份当前容器运行数据（if any）"
mkdir -p "${SCAN_DIR}/data"

echo "==> [3/4] 重建容器 ${CONTAINER}（保留 ./data 持久卷）"
# 用 docker run 重建，避免依赖 compose；数据目录挂载到宿主机 SCAN_DIR/data。
# 先删旧容器（同名冲突）。数据都在 bind mount，删除容器不丢数据。
docker rm -f "${CONTAINER}" 2>/dev/null || true

docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  -p "${PORT}:${PORT}" \
  -v "${SCAN_DIR}/data:/srv/data" \
  "${IMAGE}"

echo "==> [4/4] 健康检查"
for i in $(seq 1 20); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health" || true)
  if [ "$CODE" = "200" ]; then
    echo "健康检查通过：http://127.0.0.1:${PORT}/api/health -> 200"
    exit 0
  fi
  sleep 3
done
echo "警告：健康检查超时。请查容器日志：docker logs ${CONTAINER}"
exit 1