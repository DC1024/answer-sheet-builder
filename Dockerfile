# 答题卡制作器 —— 纯静态站点，nginx 托管
# 制作器入口为 app.html；镜像内将其作为站点首页，故容器 / 直接就是制作器。
FROM nginx:alpine

COPY app.html /usr/share/nginx/html/index.html
COPY assets /usr/share/nginx/html/assets

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
