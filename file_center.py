import requests
import json
import time
from pathlib import Path
from module.utils import to_list
from loguru import logger

SUPPORTED_EXTS = {'pdf', 'jpg', 'jpeg', 'png', 'docx', 'txt','zip', 'rar'}
COMPRESS_EXTS = {'zip', 'rar'}
SUPPORTED_EXTS |= COMPRESS_EXTS

class FileCenter():
    def __init__(self, host, port, timeout=120):
        self.host = host
        self.port = port
        self.getFilesByIdsUrl = f'http://{host}:{port}/files/ids'
        self.downloadUrl = f'http://{host}:{port}/files/' + '{id}'
        self.uploadUrl = f'http://{host}:{port}/files/upload'
        self.timeout = timeout

        log_name = 'file_center'
        logger.add(f"logs/module_{log_name}_{{time:YYYY-MM-DD}}.log",
               level="INFO",
               rotation="00:00",
               filter=lambda record: record["extra"].get("name") == log_name,
               enqueue=False,
               buffering=1)
        self.logger = logger.bind(name=log_name)

    def get_files_info(self, fileIds, retry_count=3, retry_delay=3):
        """
        获取文件信息，支持重试机制。

        :param fileIds: 文件 ID 列表或单个 ID
        :param retry_count: 最大重试次数
        :param retry_delay: 失败后等待的秒数
        :return: 成功返回 JSON 数据，失败抛出异常
        """
        fileIds = to_list(fileIds)

        data = {"ids": fileIds}
        last_exception = None  # 用于存储最后一次异常

        for attempt in range(1, retry_count + 1):
            try:
                response = requests.post(self.getFilesByIdsUrl, json=data, timeout=self.timeout)
                response.raise_for_status()  # 确保响应状态码为 2xx
                self.logger.info(f'获取文件信息成功：{fileIds}')
                return response.json()['datas']  # 请求成功，返回结果
                # {'datas': [{'id': 'ca806ed797ad429b86bf811b9b67560f',
                #    'name': '前端开发规范集成指南-新版.pdf',
                #    'isImg': False,
                #    'contentType': 'application/pdf',
                #    'size': 1708557,
                #    'path': '1742453008595_3978201551408326_前端开发规范集成指南-新版.pdf',
                #    'url': 'null/前端开发规范集成指南-新版.pdf',
                #    'source': 'huawei',
                #    'createTime': '2025-03-20T06:43:28.000+0000',
                #    'updateTime': '2025-03-20T06:43:29.000+0000'}],
                #  'resp_code': 0,
                #  'resp_msg': ''}

            except requests.Timeout:
                last_exception = requests.Timeout("请求超时")
                self.logger.warning(f"请求文件超时，正在进行第 {attempt}/{retry_count} 次重试...")

            except requests.RequestException as e:
                last_exception = e
                self.logger.warning(f"请求文件失败: {e}，正在进行第 {attempt}/{retry_count} 次重试...")

            if attempt < retry_count:
                time.sleep(retry_delay)  # 等待后重试

        self.logger.error(f'请求失败，已重试 {retry_count} 次但未成功：{fileIds}')
        # 若所有尝试都失败，抛出最后一次异常
        raise last_exception if last_exception else Exception(f"请求失败，已重试 {retry_count} 次但未成功")

    def download_file(self, file_id, file_path, retry_count=3, retry_delay=3):
        """
        从指定URL下载文件，并支持失败重试。

        :param download_url: 下载链接格式，如 "https://example.com/download/{id}"
        :param file_id: 文件ID
        :param file_path: 保存的本地路径
        :param retry_count: 最大重试次数
        :param retry_delay: 失败后等待的秒数
        """
        url = self.downloadUrl.format(id=file_id)

        for attempt in range(1, retry_count + 1):
            try:
                response = requests.get(url, stream=True, timeout=self.timeout)  # 添加超时
                if response.status_code == 200:
                    with open(file_path, "wb") as file:
                        for chunk in response.iter_content(chunk_size=8192):
                            file.write(chunk)
                    self.logger.info(f"下载完成: {file_id} {file_path}")
                    return True  # 下载成功
                else:
                    self.logger.error(f"下载失败，状态码: {response.status_code}")

            except requests.Timeout:
                self.logger.warning(f"请求超时，正在进行第 {attempt}/{retry_count} 次重试...")
            except requests.RequestException as e:
                self.logger.warning(f"下载失败: {e}，正在进行第 {attempt}/{retry_count} 次重试...")

            if attempt < retry_count:
                time.sleep(retry_delay)  # 等待后重试

        self.logger.error(f"下载失败，已重试{retry_count}次仍未成功：{file_id} {file_path}")
        return False  # 下载失败

    def upload_file(self, file_path, retry_count=3, retry_delay=3):
        file_path = Path(file_path)
        suffix = file_path.suffix.lstrip('.')

        datas = {"title": "上传文件获取文件id", "fileType": suffix}

        for attempt in range(1, retry_count + 1):
            try:
                with open(file_path, 'rb') as f:
                    files_report = {'file': (file_path.name, f, suffix)}
                    response = requests.post(self.uploadUrl, files=files_report, data=datas, timeout=self.timeout)
                    response.raise_for_status()  # 确保响应状态码为 2xx
                    self.logger.info(f'上传文件成功：{file_path}')
                    return response.json().get('id')  # 请求成功，返回文件id
            except requests.Timeout:
                self.logger.warning(f"请求超时，正在进行第 {attempt}/{retry_count} 次重试...")
                if attempt < retry_count:
                    time.sleep(retry_delay)  # 增加延迟再重试
            except requests.RequestException as e:
                self.logger.warning(f"请求失败: {e}")
                break  # 遇到非超时的错误，直接终止
        self.logger.error(f'上传文件失败，已重试{retry_count}次仍未成功：{file_path}')
        return None  # 所有重试都失败，返回 None

    """
    {'datas': [{'id': 'ca806ed797ad429b86bf811b9b67560f',
       'name': '前端开发规范集成指南-新版.pdf',
       'isImg': False,
       'contentType': 'application/pdf',
       'size': 1708557,
       'path': '1742453008595_3978201551408326_前端开发规范集成指南-新版.pdf',
       'url': 'null/前端开发规范集成指南-新版.pdf',
       'source': 'huawei',
       'createTime': '2025-03-20T06:43:28.000+0000',
       'updateTime': '2025-03-20T06:43:29.000+0000'}],
     'resp_code': 0,
     'resp_msg': ''}
    """

    def extract_id_name_mapping(self, datas):
        """
        提取文件id和名称映射关系
        """
        result_Dict = {}
        for data in datas:
            if Path(data['name']).suffix.lstrip('.').lower() not in SUPPORTED_EXTS:
                continue
            if data['name'] in result_Dict.values():
                path = Path(data['name'])
                number_suffix = 1
                while True:
                    if f'{path.stem}_{number_suffix:03d}{path.suffix}' in result_Dict.values():
                        number_suffix += 1
                    else:
                        break
                result_Dict[data['id']] = f'{path.stem}_{number_suffix:03d}{path.suffix}'
            else:
                result_Dict[data['id']] = data['name']
        return result_Dict

    def download_files(self, id_name_mapping, save_dir, retry_count=3, retry_delay=3):
        """
        批量下载多个文件。

        :param id_name_mapping: {file_id: file_name} 映射
        :param save_dir: 本地保存目录
        :param retry_count: 最大重试次数
        :param retry_delay: 失败后等待时间
        :return: 成功和失败的文件列表
        """
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        success_list, failure_list = [], []

        for file_id, file_name in id_name_mapping.items():
            file_path = save_dir / file_name  # 生成完整的本地文件路径
            self.logger.info(f"开始下载文件: {file_name} (ID: {file_id}) 到 {file_path}")

            if self.download_file(file_id, file_path, retry_count, retry_delay):
                success_list.append(file_id)
                self.logger.info(f"文件下载成功: {file_name}")
            else:
                failure_list.append(file_id)
                self.logger.error(f"文件下载失败: {file_name}")

        self.logger.info(f"下载完成，成功: {len(success_list)} 个，失败: {len(failure_list)} 个")
        return success_list, failure_list
