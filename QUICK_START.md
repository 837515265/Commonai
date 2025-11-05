# 快速启动指南

## 🚀 一键启动（推荐）

```bash
# 进入项目目录
cd /app-test/common-ai/common-ai

# 运行快速启动脚本
./quick_start.sh

# 选择选项 7（完整流程）
```

## 📝 手动启动步骤

### 1. 配置修改（必需）

编辑 `config/local.toml`，修改以下地址：
- 文件中心地址：`[static.common-file-center]`
- 回调服务地址：`[static.app-ai-center-service]`
- LLM 服务地址：`[openai].base_url`
- OCR 服务地址（如果使用）：`[ocrvl].server_url`

### 2. 构建和启动

```bash
# 首次构建（需要 10-30 分钟）
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 3. 测试

```bash
# 运行测试脚本
python3 test_api.py

# 或访问 API 文档
# 浏览器打开: http://localhost:20001/docs
```

## 🔧 常用命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 重新构建（修改代码后）
docker-compose build
docker-compose up -d

# 查看容器状态
docker-compose ps

# 进入容器
docker exec -it common-ai bash

# 检查 GPU
docker exec -it common-ai nvidia-smi
```

## 📋 测试脚本配置

编辑 `test_api.py`，修改以下配置：

```python
# 1. 服务器地址
servers = {
    "本地服务器": "http://localhost:20001",
    "远程服务器": "http://YOUR_SERVER_IP:20001"  # 修改这里
}

# 2. 测试文件ID
test_files = [
    {
        "fileId": "YOUR_FILE_ID",  # 修改为实际文件ID
        "ocrFileId": ""
    }
]
```

## ⚠️ 注意事项

1. **GPU**: 确保使用 GPU2（已配置 `CUDA_VISIBLE_DEVICES=2`）
2. **端口**: 默认端口 20001，确保未被占用
3. **配置文件**: 根据实际环境修改配置文件
4. **文件ID**: 测试时使用实际的文件中心中的文件ID
5. **网络**: 确保容器可以访问文件中心、LLM 和回调服务

## 🐛 常见问题

### 端口被占用
```bash
# 修改 docker-compose.yml 中的端口映射
ports:
  - "20002:20001"  # 改为其他端口
```

### GPU 不可用
```bash
# 检查 NVIDIA Container Toolkit
nvidia-container-cli --version

# 重启 Docker
sudo systemctl restart docker
```

### 服务启动失败
```bash
# 查看详细日志
docker-compose logs -f common-ai

# 检查配置文件
cat config/local.toml
```

## 📚 详细文档

查看 [RUN_GUIDE.md](RUN_GUIDE.md) 获取完整文档。

