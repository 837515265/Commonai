# 项目运行指南

## 📋 目录
1. [环境准备](#环境准备)
2. [配置说明](#配置说明)
3. [Docker 构建和运行](#docker-构建和运行)
4. [测试验证](#测试验证)
5. [常见问题](#常见问题)

---

## 🛠️ 环境准备

### 1. 系统要求
- **操作系统**: Linux (Ubuntu 20.04+ 推荐)
- **GPU**: NVIDIA A800 (使用 GPU2)
- **Docker**: 20.10+
- **Docker Compose**: 1.29+
- **NVIDIA Container Toolkit**: 已安装并配置

### 2. 检查 GPU 环境
```bash
# 检查 GPU 是否可用
nvidia-smi

# 检查 Docker 是否支持 GPU
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 3. 检查 Docker 和 Docker Compose
```bash
# 检查 Docker 版本
docker --version

# 检查 Docker Compose 版本
docker-compose --version

# 如果没有安装 docker-compose，可以安装
sudo apt-get update
sudo apt-get install docker-compose
```

---

## ⚙️ 配置说明

### 1. 修改配置文件

编辑 `config/local.toml`（或其他环境的配置文件）：

```toml
# 文件中心配置（固定地址）
[static.common-file-center]
host = "10.10.30.160"  # 修改为实际文件中心地址
port = 30080

# 回调服务配置（固定地址）
[static.app-ai-center-service]
host = "10.10.30.160"  # 修改为实际回调服务地址
port = 30080

# LLM 服务配置
[openai]
base_url = "http://127.0.0.1:21061"  # 修改为实际 LLM 服务地址
model = "qwen2.5-32b"
timeout = 120
system = "你是一名中文语言专家..."
temperature = 0.2
top_p = 0.9
max_tokens = 2048
ctx_limit = 12000

# OCR 配置（二选一）
# 方式1: 使用 PaddleOCR-VL (推荐，如果已部署 vllm 服务)
[ocrvl]
server_url = "http://127.0.0.1:8118/v1"  # 修改为实际 OCR-VL 服务地址
model_name = "PaddleOCR-VL-0.9B"
backend = "vllm-server"
save_dir = "./ocr_out"
save_mode = "json"
save_images = false
save_layout_png = false

# 方式2: 使用 PaddleX OCR (如果不配置 ocrvl，会自动使用 PaddleX)

# 回调路径配置
[callback]
final_result_path = "/v1/extract/contractResult"
ocr_result_path = "/v1/extract/ocrResult"

# 应用配置
[app]
port = 20001
```

### 2. 环境变量配置

通过环境变量 `APP_ENV` 指定使用的配置文件：
- `local` → `config/local.toml`
- `dev` → `config/dev.toml`
- `sit` → `config/sit.toml`
- `prd` → `config/prd.toml`

---

## 🐳 Docker 构建和运行

### 1. 首次构建（完整构建）

```bash
# 进入项目目录
cd /app-test/common-ai/common-ai

# 构建 Docker 镜像（首次构建需要 10-30 分钟，取决于网络速度）
docker-compose build

# 或者使用 Docker 直接构建
docker build -t common-ai:latest .
```

**构建说明**：
- 首次构建会安装所有底层环境（系统包、Python 依赖、PaddlePaddle、PaddleX）
- 构建时间较长，请耐心等待
- 后续修改 Python 代码后，只需要重新构建最后一层（几秒到几分钟）

### 2. 启动服务

```bash
# 使用 docker-compose 启动（推荐）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 或者使用 Docker 直接运行
docker run -d \
  --name common-ai \
  --gpus '"device=2"' \
  -p 20001:20001 \
  -e APP_ENV=local \
  -e CUDA_VISIBLE_DEVICES=2 \
  -e NVIDIA_VISIBLE_DEVICES=2 \
  -v $(pwd)/logs:/home/appuser/app/logs \
  -v $(pwd)/tmp:/home/appuser/app/tmp \
  common-ai:latest
```

### 3. 检查服务状态

```bash
# 检查容器状态
docker-compose ps

# 检查容器日志
docker-compose logs -f common-ai

# 检查容器内 GPU 使用情况
docker exec -it common-ai nvidia-smi

# 检查服务是否正常启动
curl http://localhost:20001/docs
```

### 4. 停止服务

```bash
# 停止服务
docker-compose down

# 停止并删除容器
docker-compose down -v
```

### 5. 重新构建（修改代码后）

```bash
# 如果只修改了 Python 代码，重新构建会很快（使用缓存）
docker-compose build

# 重启服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

---

## 🧪 测试验证

### 1. 运行测试脚本

```bash
# 进入项目目录
cd /app-test/common-ai/common-ai

# 安装测试依赖（如果需要）
pip install requests

# 运行测试脚本
python test_api.py
```

### 2. 修改测试脚本中的服务器地址

编辑 `test_api.py`，修改服务器配置：

```python
servers = {
    "本地服务器": "http://localhost:20001",
    "远程服务器": "http://YOUR_REMOTE_SERVER_IP:20001"  # 修改为实际远程服务器地址
}
```

### 3. 修改测试文件 ID

编辑 `test_api.py` 中的 `get_test_files()` 函数，替换为实际的文件 ID：

```python
def get_test_files() -> List[Dict]:
    return [
        {
            "fileId": "YOUR_ACTUAL_FILE_ID",  # 替换为实际文件ID
            "ocrFileId": ""  # 空表示需要OCR
        }
    ]
```

### 4. 手动测试 API

#### 测试健康检查（如果有）
```bash
curl http://localhost:20001/health
```

#### 测试 API 文档
```bash
# 在浏览器中打开
http://localhost:20001/docs
```

#### 测试合同要素提取接口
```bash
curl -X POST "http://localhost:20001/v1/contract_element_extract" \
  -H "Content-Type: application/json" \
  -d '{
    "taskNo": "TEST_20250101120000",
    "files": [
      {
        "fileId": "YOUR_FILE_ID",
        "ocrFileId": ""
      }
    ],
    "config": [
      {
        "fieldKey": "借款金额",
        "fieldKeyType": "1",
        "nearFieldKeys": ["借款合同金额", "合同金额"],
        "fieldValueOptions": [],
        "description": "借款合同中的借款金额"
      }
    ],
    "prompt": ""
  }'
```

### 5. 从远程服务器测试

```bash
# 在远程服务器上运行测试脚本
ssh user@remote_server
cd /path/to/common-ai
python test_api.py
```

或者在本地测试远程服务器：

```bash
# 修改 test_api.py 中的服务器地址为远程地址
python test_api.py
```

---

## 🔍 常见问题

### 1. GPU 不可用

**问题**: 容器无法使用 GPU

**解决方案**:
```bash
# 检查 NVIDIA Container Toolkit 是否安装
nvidia-container-cli --version

# 如果没有安装，安装它
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 2. 端口被占用

**问题**: 端口 20001 已被占用

**解决方案**:
```bash
# 检查端口占用
sudo lsof -i :20001

# 修改 docker-compose.yml 中的端口映射
# 将 "20001:20001" 改为 "20002:20001"（或其他可用端口）
```

### 3. 配置文件不存在

**问题**: 启动时提示配置文件不存在

**解决方案**:
```bash
# 检查配置文件是否存在
ls -la config/

# 确保有对应环境的配置文件
# 例如：config/local.toml, config/dev.toml 等

# 设置环境变量
export APP_ENV=local
```

### 4. 依赖安装失败

**问题**: 构建时 Python 依赖安装失败

**解决方案**:
```bash
# 检查网络连接
ping mirrors.ustc.edu.cn

# 如果网络有问题，可以修改 Dockerfile 中的 pip 源
# 或者使用代理
```

### 5. OCR 服务不可用

**问题**: OCR 初始化失败

**解决方案**:
```bash
# 检查 OCR 服务配置
# 如果使用 PaddleOCR-VL，确保 vllm 服务已启动
# 如果使用 PaddleX，确保模型文件已正确配置

# 检查日志
docker-compose logs -f common-ai | grep -i ocr
```

### 6. 文件中心连接失败

**问题**: 无法从文件中心下载文件

**解决方案**:
```bash
# 检查配置文件中的文件中心地址是否正确
# 检查网络连接
curl http://10.10.30.160:30080/files/ids

# 检查防火墙设置
```

### 7. 回调服务不可用

**问题**: 结果无法回调

**解决方案**:
```bash
# 检查配置文件中的回调服务地址是否正确
# 检查回调服务是否正常运行
curl http://10.10.30.160:30080/v1/extract/contractResult

# 检查日志
docker-compose logs -f common-ai | grep -i callback
```

---

## 📊 监控和日志

### 查看实时日志
```bash
docker-compose logs -f common-ai
```

### 查看特定模块日志
```bash
# OCR 日志
tail -f logs/module_OCR_*.log

# 回调日志
tail -f logs/module_callback_*.log

# 文件中心日志
tail -f logs/module_file_center_*.log
```

### 查看容器资源使用
```bash
# CPU 和内存使用
docker stats common-ai

# GPU 使用
docker exec -it common-ai nvidia-smi
```

---

## 🚀 快速启动命令总结

```bash
# 1. 进入项目目录
cd /app-test/common-ai/common-ai

# 2. 构建镜像（首次）
docker-compose build

# 3. 启动服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 运行测试
python test_api.py

# 6. 停止服务
docker-compose down
```

---

## 📝 注意事项

1. **GPU 配置**: 确保使用 GPU2（A800），已通过 `CUDA_VISIBLE_DEVICES=2` 配置
2. **配置文件**: 根据实际环境修改配置文件中的服务地址
3. **文件 ID**: 测试时需要使用实际的文件中心中的文件 ID
4. **网络**: 确保容器可以访问文件中心、LLM 服务和回调服务
5. **回调结果**: 接口是异步的，结果通过回调返回，请确保回调服务正常运行

---

## 🔗 相关文档

- [重构总结](REFACTORING_SUMMARY.md)
- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [测试脚本](test_api.py)

