#!/bin/bash

# 固定使用 GPU 环境（A800 GPU2）
VENV_PATH="/opt/venv"

# 检查虚拟环境是否存在
if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at $VENV_PATH"
    exit 1
fi

# 激活虚拟环境
source "$VENV_PATH/bin/activate"

# 生成 OCR YAML 配置（使用 GPU 模式）
python generate_OCR_yaml.py

# 执行 Python 代码，并用 exec 确保进程接管
exec python main.py
