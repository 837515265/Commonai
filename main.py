# main.py
"""
合同要素提取服务主入口
业务逻辑：PDF OCR -> Prompt拼接 -> LLM调用 -> 结果返回
"""
from pathlib import Path
import json
import os
import time
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from transformers import AutoTokenizer
from loguru import logger
from typing import List

from module.config_loader import ConfigLoader
from module.callback import CallbackClient
from module.file_center import FileCenter
from module.ocr import OcrTool, OcrError
from module.ocrvl import OcrVL as OcrVLClient
from module.llm_openai import OpenAICompatClient
from module.extractor import ElementExtractor
from module.utils import delete_path
from module.seal import SealTool

####################################
app = FastAPI(
    title='Contract Element Extract',
    description='合同要素提取',
    version='1.0.0',
    docs_url='/docs',
    redoc_url='/redocs',
)

# 文件白名单
SUPPORTED_EXTS = {'pdf', 'jpg', 'jpeg', 'png', 'docx', 'txt'}
COMPRESS_EXTS = {'zip', 'rar'}
SUPPORTED_EXTS |= COMPRESS_EXTS

# 日志
logger.remove()
logger.add(
    'logs/log_{time:YYYY-MM-DD}.log',
    rotation="00:00",
    level="INFO",
)
logger.info("Application startup initiated.")

####################################
# 数据模型
class FileMapping(BaseModel):
    fileId: str = Field(...)
    ocrFileId: str = Field(...)


class Element(BaseModel):
    fieldKey: str = Field(...)
    fieldKeyType: str = Field(...)
    nearFieldKeys: List[str] = Field(...)
    fieldValueOptions: List[str] = Field(default=[])
    description: str = Field(...)


class InputRequest(BaseModel):
    files: List[FileMapping] = Field(...)
    prompt: str = Field(default='')
    config: List[Element] = Field(...)
    taskNo: str = Field(...)

####################################
# 工作目录
tmp_file_folder = Path('./tmp')
tmp_file_folder.mkdir(exist_ok=True, parents=True)
ocr_txt_folder = Path('./ocr')
ocr_txt_folder.mkdir(exist_ok=True, parents=True)

# 全局变量
config_loader: ConfigLoader = None
ocr_tool: OcrTool = None
seal_tool: SealTool = None
llm_client: OpenAICompatClient = None
tokenizer = None
extractor: ElementExtractor = None
callback_client: CallbackClient = None
file_center: FileCenter = None

####################################
@app.on_event("startup")
def startup_event():
    """应用启动时初始化各组件"""
    global config_loader, ocr_tool, llm_client, tokenizer, extractor, callback_client, file_center, seal_tool
    
    # 1. 加载配置
    env = os.environ.get('APP_ENV', 'local')
    config_loader = ConfigLoader(env=env)
    logger.info(f"配置加载完成，环境: {env}")
    
    # 2. 初始化Seal工具（可选）
    try:
        logger.info("Initializing SealTool ...")
        seal_tool = SealTool(margin=8)
        logger.info("SealTool initialized successfully.")
    except Exception as e:
        logger.warning(f"SealTool初始化失败（跳过）: {str(e)}")
        seal_tool = None
    
    # 3. 初始化OCR工具（从配置文件读取，支持PaddleOCR-VL）
    ocrvl_cfg = config_loader.get_ocrvl_config()
    if ocrvl_cfg and ocrvl_cfg.get('server_url'):
        # 使用PaddleOCR-VL（从配置文件读取）
        try:
            logger.info("Initializing PaddleOCR-VL (from config)...")
            ocr_tool = OcrVLClient(
                server_url=ocrvl_cfg.get('server_url'),
                model_name=ocrvl_cfg.get('model_name', 'PaddleOCR-VL-0.9B'),
                backend=ocrvl_cfg.get('backend', 'vllm-server'),
                save_root=ocrvl_cfg.get('save_dir', './ocr_out'),
                page_break_text="\n----- PAGE BREAK -----\n",
                raise_error=True,
                save_mode=ocrvl_cfg.get('save_mode', 'json'),
                save_images=ocrvl_cfg.get('save_images', False),
                save_layout_png=ocrvl_cfg.get('save_layout_png', False)
            )
            logger.info(f"PaddleOCR-VL initialized successfully: {ocrvl_cfg.get('server_url')}")
        except Exception as e:
            logger.error(f"PaddleOCR-VL初始化失败: {str(e)}", exc_info=True)
            raise RuntimeError("PaddleOCR-VL initialization failed.")
    else:
        # 回退到PaddleX OCR（如果没有配置ocrvl）
        try:
            logger.info("Initializing PaddleX OCR (fallback)...")
            from paddlex import create_pipeline
            pipeline = create_pipeline("OCR.yaml")
            ocr_tool = OcrTool(pipeline=pipeline)
            logger.info("PaddleX OCR initialized successfully.")
        except Exception as e:
            logger.error(f"PaddleX OCR初始化失败: {str(e)}", exc_info=True)
            raise RuntimeError("OCR initialization failed.")
    
    # 4. 初始化LLM客户端（从配置文件读取）
    openai_cfg = config_loader.get_openai_config()
    if not openai_cfg.get("base_url"):
        raise ValueError("配置文件中未找到LLM地址，请检查 [openai] base_url 配置")
    llm_client = OpenAICompatClient(
        base_url=openai_cfg["base_url"],
        model=openai_cfg["model"],
        timeout=openai_cfg.get("timeout", 120),
        system=openai_cfg.get("system", ""),
        temperature=openai_cfg.get("temperature", 0.2),
        top_p=openai_cfg.get("top_p", 0.9),
        max_tokens=openai_cfg.get("max_tokens", 2048),
        api_key=openai_cfg.get("api_key"),
    )
    ctx_limit = int(openai_cfg.get("ctx_limit", 16000))
    logger.info(f"LLM客户端初始化完成: {openai_cfg['base_url']}, model={openai_cfg['model']}")
    
    # 5. 初始化tokenizer（用于估算token数）
    tokenizer_model = config_loader.get_tokenizer_config().get('model')
    if tokenizer_model:
        while True:
            try:
                tokenizer_obj = AutoTokenizer.from_pretrained(
                    tokenizer_model, cache_dir='./huggingface/hub'
                )
                globals()["tokenizer"] = tokenizer_obj
                logger.info("Tokenizer初始化完成")
                break
            except Exception as e:
                logger.warning(f"Tokenizer初始化失败，重试中...: {e}")
                time.sleep(2)
    else:
        globals()["tokenizer"] = None
        logger.warning("未配置tokenizer，将使用粗略估算")
    
    # 6. 初始化文件中心客户端（固定地址）
    fc_config = config_loader.get_file_center_config()
    file_center = FileCenter(
        host=fc_config['host'],
        port=fc_config['port'],
        timeout=120
    )
    logger.info(f"文件中心客户端初始化完成: {fc_config['host']}:{fc_config['port']}")
    
    # 7. 初始化回调客户端（固定地址）
    cb_config = config_loader.get_callback_config()
    callback_client = CallbackClient(
        callback_host=cb_config['host'],
        callback_port=cb_config['port'],
        final_result_path=cb_config['final_result_path'],
        ocr_result_path=cb_config['ocr_result_path']
    )
    logger.info(f"回调客户端初始化完成: {cb_config['host']}:{cb_config['port']}")
    
    # 8. 初始化要素提取器
    extractor = ElementExtractor(
        ocr_tool=ocr_tool,
        llm_client=llm_client,
        file_center=file_center,
        tokenizer=tokenizer,
        ctx_limit=ctx_limit,
        seal_tool=seal_tool
    )
    logger.info("要素提取器初始化完成")
    logger.info("应用启动完成")

####################################
def async_contract_element_extract(input_request: InputRequest):
    """
    异步处理合同要素提取任务
    业务逻辑：
    1. 从文件中心下载PDF文件
    2. 对PDF进行整体OCR
    3. 拼接prompt模板
    4. 调用大模型提取要素
    5. 返回结果（通过回调）
    """
    task_no = input_request.taskNo
    files = input_request.files
    extra_prompt = input_request.prompt
    config = input_request.config
    
    # 任务目录
    task_file_folder = tmp_file_folder / task_no
    task_file_folder.mkdir(exist_ok=True, parents=True)
    task_ocr_txt_folder = ocr_txt_folder / task_no
    task_ocr_txt_folder.mkdir(exist_ok=True, parents=True)
    
    try:
        total_start_time = time.time()
        
        # 1. 处理文件：从文件中心下载或使用已有OCR结果
        input_ocr_result_mapping_dict = {}
        to_ocr_file_id_list, ocr_txt_file_id_list = [], []
        
        for fm in files:
            if not fm.ocrFileId:
                to_ocr_file_id_list.append(fm.fileId)
                input_ocr_result_mapping_dict[fm.fileId] = ''
            else:
                ocr_txt_file_id_list.append(fm.ocrFileId)
                input_ocr_result_mapping_dict[fm.fileId] = fm.ocrFileId
        
        logger.info(f'{task_no}：待OCR文件={to_ocr_file_id_list}')
        logger.info(f'{task_no}：已有OCR文件={ocr_txt_file_id_list}')
        
        # 下载已有OCR的txt文件
        get_files_start_time = time.time()
        ocr_txt_file_mapping_dict = {}
        if ocr_txt_file_id_list:
            try:
                ocr_txt_file_info_list = file_center.get_files_info(fileIds=ocr_txt_file_id_list)
                ocr_txt_file_mapping_dict = file_center.extract_id_name_mapping(ocr_txt_file_info_list)
                ocr_ok, ocr_fail = file_center.download_files(
                    id_name_mapping=ocr_txt_file_mapping_dict,
                    save_dir=task_file_folder
                )
                logger.info(f'{task_no}：OCR文件下载结果：成功={ocr_ok}, 失败={ocr_fail}')
                new_to_ocr = [fid for fid, ofid in input_ocr_result_mapping_dict.items() if ofid in ocr_fail]
            except Exception as e:
                logger.error(f'{task_no}：获取已OCR文件失败: {e}')
                callback_client.send_error_result(task_no, '获取文件失败')
                return
        else:
            new_to_ocr = []
        
        # 下载待OCR的原始文件
        to_ocr_file_mapping_dict = {}
        if to_ocr_file_id_list + new_to_ocr:
            try:
                to_ocr_file_info_list = file_center.get_files_info(fileIds=to_ocr_file_id_list + new_to_ocr)
                to_ocr_file_mapping_dict = file_center.extract_id_name_mapping(to_ocr_file_info_list)
                
                # 检查文件类型
                for item in to_ocr_file_info_list:
                    suffix = Path(item['name']).suffix.lstrip('.').lower()
                    if suffix not in SUPPORTED_EXTS:
                        callback_client.send_error_result(task_no, f'文件类型不支持: {suffix}')
                        return
                
                ok, fail = file_center.download_files(
                    id_name_mapping=to_ocr_file_mapping_dict,
                    save_dir=task_file_folder
                )
                if fail or not ok:
                    logger.error(f'{task_no}：原文件下载失败：{fail}')
                    callback_client.send_error_result(task_no, '获取文件失败')
                    return
            except Exception as e:
                logger.error(f'{task_no}：下载文件失败: {e}')
                callback_client.send_error_result(task_no, '获取文件失败')
                return
        
        get_files_end_time = time.time()
        logger.info(f'{task_no}：获取文件耗时：{get_files_end_time - get_files_start_time:.2f}s')
        
        # 组装文件路径映射（存储相对于task_file_folder的文件名）
        file_id_name_mapping_dict = {}
        for fm in files:
            fid, ofid = fm.fileId, fm.ocrFileId
            if ofid in ocr_txt_file_mapping_dict:
                # 文件已经下载到task_file_folder，存储文件名即可
                file_id_name_mapping_dict[fid] = ocr_txt_file_mapping_dict[ofid]
            elif fid in to_ocr_file_mapping_dict:
                file_id_name_mapping_dict[fid] = to_ocr_file_mapping_dict[fid]
        
        logger.info(f'{task_no}：文件映射={file_id_name_mapping_dict}')
        
        # 2. 执行要素提取（OCR -> Prompt -> LLM -> 返回）
        try:
            result_json = extractor.extract(
                files=files,
                config=config,
                extra_prompt=extra_prompt,
                task_no=task_no,
                task_file_folder=task_file_folder,
                task_ocr_txt_folder=task_ocr_txt_folder,
                file_id_name_mapping_dict=file_id_name_mapping_dict
            )
            
            # 检查结果是否全为空
            result_dict = json.loads(result_json)
            if all(map(lambda x: x == '', result_dict.values())):
                logger.warning(f'{task_no}：大模型提取要素结果全为空')
                callback_client.send_error_result(task_no, '大模型提取要素结果全为空')
                return
            
            # 3. 上传OCR结果（如果需要）
            # TODO: 如果需要上传OCR结果，可以在这里添加逻辑
            
            # 4. 返回最终结果
            callback_client.send_normal_result(task_no, result_json)
            
            total_end_time = time.time()
            logger.info(f'{task_no}：任务总时间：{total_end_time - total_start_time:.2f}s')
            
        except ValueError as e:
            logger.error(f'{task_no}：提取失败: {e}')
            callback_client.send_error_result(task_no, str(e))
        except Exception as e:
            logger.error(f'{task_no}：提取过程发生错误: {e}', exc_info=True)
            callback_client.send_error_result(task_no, '大模型提取要素失败')
    
    finally:
        # 清理临时文件
        try:
            delete_path(task_file_folder)
            delete_path(task_ocr_txt_folder)
        except Exception:
            pass

####################################
@app.post('/v1/contract_element_extract')
def contract_element_extract(input_request: InputRequest, background_tasks: BackgroundTasks):
    """合同要素提取接口"""
    try:
        task_no = input_request.taskNo
        logger.info(f'{task_no}：请求已接收')
        data = {'message': f'任务{task_no}已接受', 'code': 0}
        background_tasks.add_task(async_contract_element_extract, input_request)
        return JSONResponse(content=data, status_code=200)
    except Exception as e:
        logger.exception(e)
        data = {'message': f'任务{getattr(input_request, "taskNo", "")}参数解析失败', 'code': 1}
        return JSONResponse(content=data, status_code=200)

####################################
if __name__ == "__main__":
    env = os.environ.get('APP_ENV', 'local')
    config = ConfigLoader(env=env)
    app_config = config.get_app_config()
    logger.info("Starting FastAPI server...")
    uvicorn.run(
        'main:app',
        host='0.0.0.0',
        port=app_config.get('port', 20001),
        reload=False,
        access_log=True,
        log_level="info"
    )
