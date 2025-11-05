# module/extractor.py
"""
要素提取模块：处理PDF OCR -> Prompt -> LLM -> 返回的核心业务逻辑
"""
import json
import re
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
from loguru import logger

from module.utils import convert_to_date, convert_to_number, extract_valid_id_numbers
from module.Prompt import contract_element_extract_prompt_pattern
from module.ocr import OcrTool, OcrError
from module.llm_openai import OpenAICompatClient
from module.file_center import FileCenter


class ElementExtractor:
    """合同要素提取器：封装完整的提取流程"""
    
    def __init__(
        self,
        ocr_tool: OcrTool,
        llm_client: OpenAICompatClient,
        file_center: Optional[FileCenter] = None,
        tokenizer=None,
        ctx_limit: int = 16000,
        seal_tool=None
    ):
        """
        :param ocr_tool: OCR工具
        :param llm_client: 大模型客户端
        :param file_center: 文件中心客户端（可选）
        :param tokenizer: tokenizer（用于估算token数）
        :param ctx_limit: 上下文限制
        :param seal_tool: 印章识别工具（可选）
        """
        self.ocr_tool = ocr_tool
        self.llm_client = llm_client
        self.file_center = file_center
        self.tokenizer = tokenizer
        self.ctx_limit = ctx_limit
        self.seal_tool = seal_tool
    
    def _get_tokens_num(self, text: str) -> int:
        """估算token数量"""
        if self.tokenizer is None:
            return len(text)  # 粗略估算
        try:
            return len(self.tokenizer.encode(text))
        except Exception:
            return len(text)
    
    def _build_schema_prompt(self, config: List) -> Tuple[str, Dict[str, List[str]], Dict[str, List[str]]]:
        """构建schema提示词"""
        text_schema = [i.fieldKey for i in config if i.fieldKeyType == '0']
        money_schema = [i.fieldKey for i in config if i.fieldKeyType == '1']
        date_schema = [i.fieldKey for i in config if i.fieldKeyType == '2']
        interval_schema = [i.fieldKey for i in config if i.fieldKeyType == '3']
        
        schema_dict = {
            '文本字段': text_schema,
            '金额字段': money_schema,
            '日期字段': date_schema,
            '时间段字段': interval_schema
        }
        synonym_dict = {i.fieldKey: i.nearFieldKeys for i in config if i.nearFieldKeys}
        
        schema_prompt = ''
        for category in schema_dict:
            if schema_dict[category]:
                schema_prompt += f'\n\n### **{category}**'
                for schema in schema_dict[category]:
                    schema_prompt += f'\n- **{schema}**'
                    if schema in synonym_dict:
                        synonym = '，'.join(synonym_dict[schema])
                        schema_prompt += f'（可能的近义词:{synonym}）'
        
        return schema_prompt.strip(), schema_dict, synonym_dict
    
    def _extract_prefilled_fields(
        self,
        config: List[Any],
        doc_text: str,
        filename_list: List[Path],
        task_file_folder: Path,
        valid_id_map: Dict[str, str]
    ) -> Dict[str, str]:
        """提取预填充字段（主银行、身份证号等）"""
        prefilled: Dict[str, str] = {}
        
        type4_fields = [e.fieldKey for e in config if e.fieldKeyType == '4']  # 主银行
        type5_fields = [e.fieldKey for e in config if e.fieldKeyType == '5']  # 身份证
        
        # 主银行识别
        if type4_fields and self.seal_tool is not None:
            try:
                seal_input_files: List[Path] = []
                for fn in filename_list:
                    fn_path = Path(fn)
                    suf = fn_path.suffix.lower().lstrip(".")
                    if suf in {"pdf", "png", "jpg", "jpeg"}:
                        if fn_path.is_absolute():
                            seal_input_files.append(fn_path)
                        else:
                            seal_input_files.append(task_file_folder / fn_path)
                
                all_best: List[str] = []
                for fp in seal_input_files:
                    seal_out_dir = task_file_folder / "seal_out" / fp.stem
                    seal_out_dir.mkdir(parents=True, exist_ok=True)
                    r = self.seal_tool.extract_from_file(fp, out_dir=seal_out_dir)
                    if r.get("best_bank"):
                        all_best.append(r["best_bank"])
                
                if all_best:
                    from collections import Counter
                    cnt = Counter(all_best)
                    main_bank_name = max(cnt.keys(), key=lambda k: (cnt[k], len(k)))
                    if main_bank_name:
                        for k in type4_fields:
                            prefilled[k] = main_bank_name
            except Exception as e:
                logger.warning(f'Seal 主银行识别失败（跳过）: {e}')
        
        # 身份证号
        if type5_fields:
            all_ids = list(valid_id_map.keys()) if isinstance(valid_id_map, dict) else []
            ids_joined = "、".join(all_ids)
            for k in type5_fields:
                prefilled[k] = ids_joined
            if ids_joined:
                logger.info(f'直填身份证号：{ids_joined}')
        
        return prefilled
    
    def extract(
        self,
        files: List[Any],
        config: List[Any],
        extra_prompt: str,
        task_no: str,
        task_file_folder: Path,
        task_ocr_txt_folder: Path,
        file_id_name_mapping_dict: Dict[str, str]
    ) -> str:
        """
        执行完整的提取流程：
        1. 对PDF进行整体OCR
        2. 拼接prompt模板
        3. 调用大模型
        4. 返回结果
        """
        # 1. 字段分组和schema构建
        schema_prompt, schema_dict, synonym_dict = self._build_schema_prompt(config)
        text_schema = schema_dict['文本字段']
        money_schema = schema_dict['金额字段']
        date_schema = schema_dict['日期字段']
        
        # 2. 组装文件路径列表（使用本地文件名）
        filename_list: List[Path] = []
        for fm in files:
            fid = fm.fileId
            if fid in file_id_name_mapping_dict:
                # file_id_name_mapping_dict存储的是文件名，需要加上任务目录
                local_filename = file_id_name_mapping_dict[fid]
                filename_list.append(Path(local_filename))
        
        # 3. 对PDF进行整体OCR
        try:
            logger.info(f'{task_no}：开始OCR识别')
            file_names = [''.join(re.findall(r'[\u4e00-\u9fff]', Path(fn).name)) for fn in filename_list]
            file_names = [n for n in file_names if n]
            file_names_str = "，".join(file_names) if file_names else "未检测到有效中文文件名"
            
            # 执行OCR：文件已经在task_file_folder中，使用完整路径
            ocr_file_paths = []
            for fn in filename_list:
                fn_path = Path(fn)
                if fn_path.is_absolute():
                    ocr_file_paths.append(fn_path)
                else:
                    ocr_file_paths.append(task_file_folder / fn_path)
            
            doc_text, page_text_dict = self.ocr_tool.ocr_files(ocr_file_paths)
            doc_text, page_text_dict = self.ocr_tool.remove_duplicate_sentences(doc_text, page_text_dict)
            valid_id_map = extract_valid_id_numbers(doc_text)
            
            logger.info(f'{task_no}：OCR完成，文本长度: {len(doc_text)}')
        except OcrError as e:
            logger.error(f'{task_no}：OCR失败: {e}')
            raise
        
        if not doc_text:
            raise ValueError('文件OCR内容为空')
        
        # 4. 提取预填充字段
        prefilled = self._extract_prefilled_fields(
            config, doc_text, filename_list, task_file_folder, valid_id_map
        )
        
        # 5. 构建完整prompt
        extra_prompt_text = re.sub('\n+', '\n', f'''
        ## 补充说明
        {extra_prompt}
        '''.strip()) if extra_prompt else ''
        
        clean_text = doc_text.replace(self.ocr_tool.page_break_text, '\n')
        
        full_prompt = contract_element_extract_prompt_pattern.format(
            file_names=file_names_str,
            text=clean_text,
            schema_prompt=schema_prompt,
            extra_prompt=extra_prompt_text
        )
        
        logger.info(f'{task_no}：prompt长度={len(full_prompt)}, tokens≈{self._get_tokens_num(full_prompt)}')
        
        # 6. 调用大模型
        try:
            if self._get_tokens_num(full_prompt) + 500 < self.ctx_limit:
                # 单次调用
                result_dict = self._extract_single_pass(full_prompt, prefilled, money_schema, date_schema)
            else:
                # 分段调用
                result_dict = self._extract_multi_pass(
                    page_text_dict, file_names_str, schema_prompt, extra_prompt_text,
                    prefilled, text_schema, money_schema, date_schema
                )
            
            # 7. 格式化结果
            result_json = json.dumps(result_dict, ensure_ascii=False, indent=4)
            logger.info(f'{task_no}：提取完成，结果: {result_json[:200]}...')
            
            return result_json
            
        except Exception as e:
            logger.error(f'{task_no}：大模型提取失败: {e}')
            raise
    
    def _extract_single_pass(
        self,
        full_prompt: str,
        prefilled: Dict[str, str],
        money_schema: List[str],
        date_schema: List[str]
    ) -> Dict[str, Any]:
        """单次调用大模型"""
        convert_status = False
        result_dict = {}
        
        for _ in range(3):
            try:
                result_text = self.llm_client.generate(prompt=full_prompt)
                result = OpenAICompatClient.format_LLM_result(result_text)
                result_dict = json.loads(result)
                
                # 合并直填项
                result_dict.update({k: v for k, v in prefilled.items() if v is not None})
                for k, v in result_dict.items():
                    result_dict[k] = str(v).strip('_ ')
                
                convert_status = True
                break
            except Exception as e:
                logger.error(f'JSON 解析失败: {e}')
        
        if not convert_status:
            raise RuntimeError("大模型提取要素失败")
        
        # 规范化
        for col in money_schema:
            result_dict[col] = convert_to_number(result_dict.get(col, ''), fail_return='')
        for col in date_schema:
            result_dict[col] = convert_to_date(result_dict.get(col, ''), fail_return='')
        
        return result_dict
    
    def _extract_multi_pass(
        self,
        page_text_dict: Dict[int, str],
        file_names_str: str,
        schema_prompt: str,
        extra_prompt_text: str,
        prefilled: Dict[str, str],
        text_schema: List[str],
        money_schema: List[str],
        date_schema: List[str]
    ) -> Dict[str, Any]:
        """分段调用大模型"""
        part_json_dict = {}
        part_index = 1
        current_text = ""
        last_text = ""
        
        for page_index in sorted(page_text_dict.keys()):
            page_text = page_text_dict[page_index]
            if page_index == 1:
                current_text = page_text
            else:
                last_text = current_text
                current_text += '\n\n' + page_text
            
            current_prompt = contract_element_extract_prompt_pattern.format(
                file_names=file_names_str,
                text=current_text,
                schema_prompt=schema_prompt,
                extra_prompt=extra_prompt_text
            )
            
            if self._get_tokens_num(current_prompt) + 500 >= self.ctx_limit:
                if last_text.strip():
                    input_text = contract_element_extract_prompt_pattern.format(
                        file_names=file_names_str,
                        text=last_text,
                        schema_prompt=schema_prompt,
                        extra_prompt=extra_prompt_text
                    )
                    part_text = self.llm_client.generate(prompt=input_text)
                    part_text = OpenAICompatClient.format_LLM_result(part_text)
                    part_json_dict[part_index] = part_text
                    part_index += 1
                current_text = page_text  # 新段
        
        # 最后一段
        input_text = contract_element_extract_prompt_pattern.format(
            file_names=file_names_str,
            text=current_text,
            schema_prompt=schema_prompt,
            extra_prompt=extra_prompt_text
        )
        part_text = self.llm_client.generate(prompt=input_text)
        part_text = OpenAICompatClient.format_LLM_result(part_text)
        part_json_dict[part_index] = part_text
        
        # 合并分段结果
        result_dict_all = {}
        for part_num, part_json in part_json_dict.items():
            try:
                d = json.loads(part_json)
                result_dict_all[part_num] = d
            except Exception:
                pass
        
        if not result_dict_all:
            raise RuntimeError("分段提取结果为空")
        
        df = pd.DataFrame(result_dict_all).T
        
        tmp_result = {}
        for col in money_schema + text_schema + date_schema:
            if col not in df.columns:
                tmp_result[col] = ''
                continue
            series = df[col].where(lambda x: x != '').dropna().map(str).str.strip('_ ')
            if col in money_schema:
                series = series.map(convert_to_number)
            if col in date_schema:
                series = series.map(convert_to_date)
            if series.isnull().all():
                tmp_result[col] = ''
                continue
            mode_series = series.mode(dropna=True)
            if mode_series.shape[0] > 1:
                value_list = list(series)
                value = sorted(mode_series, key=value_list.index)[0]
                tmp_result[col] = str(value)
            elif mode_series.shape[0] == 1:
                tmp_result[col] = str(mode_series.iloc[0])
            else:
                tmp_result[col] = ''
        
        tmp_result.update({k: v for k, v in prefilled.items() if v is not None})
        return tmp_result

