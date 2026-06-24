FROM python:3.11-slim

WORKDIR /app

# 复制全部项目文件
COPY . .

EXPOSE 8888

CMD ["python", "server.py"]
