# 多阶段分层构建 Dockerfile
# 优化策略：底层环境在单独层，代码文件在最后层，实现缓存优化

FROM swr.cn-north-4.myhuaweicloud.com/sdndopm/cuda:11.8.0-cudnn8-devel-ubuntu22.04-python3.11

# ============================================
# Layer 1: 系统依赖和基础环境（很少变化）
# ============================================
RUN apt-get update && \
    apt-get install -y \
        libx11-xcb1 \
        libgl1 \
        libgomp1 \
        ccache && \
    groupadd --gid 1000 appuser && \
    useradd --home-dir /home/appuser --create-home --uid 1000 --gid 1000 --shell /bin/sh --skel /dev/null appuser && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/appuser/app

# ============================================
# Layer 2: Python 依赖安装（很少变化）
# ============================================
# 先复制依赖文件
COPY requirements.txt ./requirements.txt

# 创建 GPU 虚拟环境（固定使用 GPU，A800 环境）
RUN python -m venv /opt/venv

# 升级 pip 并安装 Python 依赖包
RUN /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/web/simple

# ============================================
# Layer 3: PaddlePaddle GPU 安装（很少变化）
# ============================================
RUN /opt/venv/bin/pip install paddlepaddle-gpu==3.0.0rc1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

# ============================================
# Layer 4: PaddleX 安装（偶尔变化）
# ============================================
COPY PaddleX ./PaddleX
RUN cd ./PaddleX && \
    /opt/venv/bin/pip install -e . --ignore-installed -i https://mirrors.ustc.edu.cn/pypi/web/simple

# ============================================
# Layer 5: 配置文件和模型文件（偶尔变化）
# ============================================
COPY PaddleX_models ./PaddleX_models
COPY config ./config
COPY huggingface ./huggingface

# ============================================
# Layer 6: Python 代码和脚本（经常变化）
# ============================================
# 复制模块代码
COPY module ./module

# 复制 Python 脚本文件
COPY *.py ./

# 复制 Shell 脚本
COPY *.sh ./

# 设置执行权限
RUN chmod +x ./*.sh

# 创建工作目录（用于日志、临时文件等）
RUN mkdir -p logs tmp ocr ocr_out && \
    chown -R appuser:appuser /home/appuser/app

# 设置用户
USER appuser

# 暴露端口
EXPOSE 20001

# 设置环境变量，确保使用 GPU
ENV CUDA_VISIBLE_DEVICES=2

# 启动脚本
ENTRYPOINT ["./run.sh"]
