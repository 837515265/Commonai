# 项目重构总结

## 重构目标

1. ✅ 去掉nacos，改为固定地址调用、固定地址回调、固定地址文件中心
2. ✅ 业务逻辑保持不变：PDF整体OCR -> 拼接prompt模板 -> 调用大模型 -> 返回结果
3. ✅ 模块化：一个类型的功能抽象成一个py文件

## 主要变更

### 新增模块

1. **`module/callback.py`** - 回调模块
   - 封装了回调逻辑
   - 提供 `CallbackClient` 类，处理错误结果、正常结果、OCR结果的回调

2. **`module/config_loader.py`** - 配置管理模块
   - 统一管理配置文件的读取
   - 提供 `ConfigLoader` 类，支持嵌套key访问
   - 提供便捷方法获取各类配置（文件中心、回调、LLM等）

3. **`module/extractor.py`** - 要素提取模块
   - 封装了核心业务逻辑
   - `ElementExtractor` 类实现了完整的提取流程：
     - PDF整体OCR
     - 构建prompt
     - 调用大模型
     - 处理结果

### 修改的文件

1. **`main.py`** - 主入口文件
   - 去掉了nacos相关代码
   - 使用固定地址配置（从配置文件读取）
   - 使用新的模块化组件
   - 代码结构更清晰

2. **删除了 `module/nacos_client.py`**
   - 完全移除了nacos依赖

### 模块化结构

现在项目按照功能类型分为以下模块：

- **配置管理**: `module/config_loader.py`
- **回调处理**: `module/callback.py`
- **文件中心**: `module/file_center.py`（已有）
- **OCR处理**: `module/ocr.py`（已有）
- **LLM调用**: `module/llm_openai.py`（已有）
- **Prompt模板**: `module/Prompt.py`（已有）
- **业务逻辑**: `module/extractor.py`（新增）
- **工具函数**: `module/utils.py`（已有）

## 配置说明

所有服务地址现在都通过配置文件 `config/{ENV}.toml` 配置：

```toml
[static.common-file-center]
host = "10.10.30.160"
port = 30080

[static.app-ai-center-service]
host = "10.10.30.160"
port = 30080

[callback]
final_result_path = "/v1/extract/contractResult"
ocr_result_path = "/v1/extract/ocrResult"
```

## 业务逻辑流程

保持不变，流程如下：

1. **文件下载**：从文件中心（固定地址）下载PDF文件
2. **PDF OCR**：对PDF进行整体OCR识别
3. **构建Prompt**：将OCR结果拼接进配置好的prompt模板
4. **调用大模型**：使用固定地址调用大模型API
5. **返回结果**：通过固定回调地址返回最终结果

## 注意事项

- 配置文件路径：`config/{ENV}.toml`，其中 `ENV` 通过环境变量 `APP_ENV` 指定，默认为 `local`
- 所有服务地址都是固定配置，不再从nacos动态获取
- 业务逻辑完全保持不变，只是代码结构更模块化

