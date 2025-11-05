import os

abspath = os.path.dirname(os.path.realpath(__file__))
abspath += os.path.sep if not abspath.endswith(os.path.sep) else ''

# 固定使用 GPU 模式（A800 GPU2 环境）
is_gpu_available = True
print("使用 GPU 模式（A800 GPU2）")

#text_det_box_thresh=0.4
#text_det_unclip_ratio=1.5
#use_textline_orientation=False

yaml_content = f"""
pipeline_name: OCR

text_type: general

use_doc_preprocessor: True
use_textline_orientation: False

SubPipelines:
  DocPreprocessor:
    pipeline_name: doc_preprocessor
    use_doc_orientation_classify: True
    use_doc_unwarping: True
    SubModules:
      DocOrientationClassify:
        module_name: doc_text_orientation
        model_name: PP-LCNet_x1_0_doc_ori
        model_dir: {abspath}PaddleX_models/PP-LCNet_x1_0_doc_ori
      DocUnwarping:
        module_name: image_unwarping
        model_name: UVDoc
        model_dir: {abspath}PaddleX_models/UVDoc

SubModules:
  TextDetection:
    module_name: text_detection
    model_name: {"PP-OCRv5_server_det" if is_gpu_available else "PP-OCRv4_mobile_det"}
    model_dir: {abspath}PaddleX_models/{"PP-OCRv5_server_det" if is_gpu_available else "PP-OCRv4_mobile_det"}
    limit_side_len: 736
    limit_type: min
    max_side_limit: 4000
    thresh: 0.3
    box_thresh: 0.6
    unclip_ratio: 1.5
  TextLineOrientation:
    module_name: textline_orientation
    model_name: PP-LCNet_x0_25_textline_ori
    model_dir: {abspath}PaddleX_models/PP-LCNet_x0_25_textline_ori
    batch_size: 1
  TextRecognition:
    module_name: text_recognition
    model_name: {"PP-OCRv5_server_rec" if is_gpu_available else "PP-OCRv4_mobile_rec"}
    model_dir: {abspath}PaddleX_models/{"PP-OCRv5_server_rec" if is_gpu_available else "PP-OCRv4_mobile_rec"}
    batch_size: 1
    score_thresh: 0.0
""".strip()


with open(f'{abspath}OCR.yaml','w',encoding='utf-8') as f:
    f.write(yaml_content)
