[TOC]

# 通用AI服务接口

## 接口列表
- **合同要素提取**

## 合同要素提取
### 地址
/v1/contract_element_extract
### 参数
files：原始文件ID与ocr结果文件ID的字典
prompt：提示词
config：字段信息
taskNo：任务编号

示例：
```json
{
"files":[
    {"fileId":"1","ocr_fileId":"11"}, // 命中缓存
    {"fileId":"2","ocr_fileId":""}  // 未命中缓存
],
"prompt":"",
"config": [
       {
         "nearFieldKeys": [
           "借款合同金额",
           "合同金额"
         ],
         "fieldKey": "借款金额",
         "fieldValueOptions": [],
         "description": "",
         "fieldKeyType": "1"
       }
],
"taskNo": "CE2025032600105"
}
```

|fieldKeyType|字段类型|
|--|--|
|'0'|通用文本|
|'1'|金额|
|'2'|日期|
|'3'|时间段|

### 返回值
正常：
```json
{"message": "任务{taskNo}已接受", "code": 0}
```

异常：
```json
{"message": "任务{taskNo}参数解析失败", "code":1}
```

### 异步调用接口
提取结果接口：
/v1/extract/contractResult

正常：
```json
{
    "taskNo": "{taskNo}",
    "result": "" //提取结果
}
```

错误：
```json
{
    "taskNo": "{taskNo}",
    "errorMsg": "" //具体错误原因
}
```


ocr文件id接口：
/v1/extract/ocrResult

```json
{
    "files":[{"filfId":"{fileID}","ocrFileId":"{ocrFileId}"}]
}
```
