# module/ocrvl.py
from __future__ import annotations
import re
import shlex
import subprocess
import tempfile
import shutil
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Tuple, Optional
from loguru import logger


class OcrError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):  # noqa: D401
        return f"OcrError:{self.message}"


class OcrVL:
    """
    调用 PaddleOCR 的 `doc_parser` 子命令，后端连接 vLLM(OpenAI 兼容) 的 PaddleOCR-VL 服务。
    对外 API 与原 OcrTool 对齐：
      - 属性：page_break_text
      - 方法：ocr_files(paths) -> (doc_text, page_text_dict)
      - 方法：remove_duplicate_sentences(doc_text, page_text_dict, **kwargs)

    新增参数：
      - save_mode: "none" | "md" | "json" | "all"
          - none: 不保留任何文件（跑临时目录，读完即删）；
          - md:   仅保留 .md；
          - json: 仅保留 *_res.json；
          - all:  保留全部（但仍受 save_images / save_layout_png 限制）。
      - save_images: 是否保留页图 PNG/JPG（最耗时/耗 IO），默认 False
      - save_layout_png: 是否保留 layout 可视化 PNG（*_layout_*_res.png），默认 False
    """

    def __init__(
        self,
        server_url: str,
        model_name: str = "PaddleOCR-VL-0.9B",
        backend: str = "vllm-server",
        save_root: str | None = "./ocr_out",
        page_break_text: str = "\n----- PAGE BREAK -----\n",
        raise_error: bool = True,
        # 新增 ↓↓↓
        save_mode: str = "md",             # "none" | "md" | "json" | "all"
        save_images: bool = False,         # 是否保存页图
        save_layout_png: bool = False      # 是否保存 layout 可视化 PNG
    ):
        self.server_url = server_url
        self.model_name = model_name
        self.backend = backend
        self.save_root = Path(save_root).resolve() if save_root else None
        self.page_break_text = page_break_text
        self.raise_error = raise_error

        # 开关
        self.save_mode = save_mode.lower().strip()
        assert self.save_mode in {"none", "md", "json", "all"}, \
            f"save_mode 只支持 none|md|json|all，收到：{self.save_mode}"
        self.save_images = bool(save_images)
        self.save_layout_png = bool(save_layout_png)

        log_name = "OCR-VL"
        logger.add(
            f"logs/module_{log_name}_{{time:YYYY-MM-DD}}.log",
            level="INFO",
            rotation="00:00",
            filter=lambda record: record["extra"].get("name") == log_name,
            enqueue=False,
            buffering=1,
        )
        self._log = logger.bind(name=log_name)

    # --------- public API (兼容 OcrTool) ---------
    def ocr_files(self, file_path_list: List[Path | str]) -> Tuple[str, Dict[int, str]]:
        """
        支持图片 / PDF / 多文件。对每个输入文件调用一次 doc_parser，
        汇总其生成的 .md 文本，合并为 doc_text，并返回 page_text_dict（按顺序编号）。
        """
        file_path_list = [Path(p) for p in file_path_list]
        self._log.info(f"[ocr_files] inputs={file_path_list}")

        all_doc = ""
        page_map: Dict[int, str] = {}
        page_no = 1

        for f in file_path_list:
            if not f.exists():
                msg = f"输入文件不存在：{f}"
                self._log.error(msg)
                if self.raise_error:
                    raise OcrError(msg)
                else:
                    continue

            # 确定此次输出目录：
            # - save_mode=none 时，使用临时目录（读取后整目录删除）
            # - 其他模式：save_root/文件名去后缀
            temp_dir_obj: Optional[tempfile.TemporaryDirectory] = None
            if self.save_mode == "none" or self.save_root is None:
                temp_dir_obj = tempfile.TemporaryDirectory(prefix="ocrvl_")
                save_dir = Path(temp_dir_obj.name)
            else:
                save_dir = (self.save_root / f.stem).resolve()
                save_dir.mkdir(parents=True, exist_ok=True)

            # 调一次 doc_parser
            try:
                merged_md, md_pages = self._run_doc_parser(f, save_dir)
            finally:
                # 清理/裁剪输出（根据开关）
                try:
                    self._postprocess_outputs(save_dir)
                except Exception as ce:
                    self._log.warning(f"[cleanup] 清理输出文件时出现非致命异常：{ce}")

            # 合并内存结果
            all_doc = (all_doc + self.page_break_text + merged_md) if all_doc else merged_md
            for _, md_txt in md_pages.items():
                page_map[page_no] = md_txt
                page_no += 1

            # 如果是临时目录，直接删除
            if temp_dir_obj is not None:
                temp_dir_obj.cleanup()

        if not all_doc.strip():
            msg = "OCR-VL 成功执行但未产出 Markdown 文本"
            self._log.error(msg)
            if self.raise_error:
                raise OcrError(msg)

        return all_doc, page_map

    def remove_duplicate_sentences(
        self, doc_text: str, page_text_dict: Dict[int, str],
        most_common: int = 30, min_length: int = 5, min_count: int = 10
    ) -> Tuple[str, Dict[int, str]]:
        """
        去掉频繁重复的行（如水印/页眉页脚）。
        """
        lines = doc_text.split("\n")
        dups = self._get_duplicate_lines(lines, most_common, min_length, min_count)
        if dups:
            lines = [ln for ln in lines if ln not in dups]
            doc_text = "\n".join(lines)
            for k in list(page_text_dict.keys()):
                p_lines = page_text_dict[k].split("\n")
                page_text_dict[k] = "\n".join([ln for ln in p_lines if ln not in dups])
        return doc_text, page_text_dict

    # --------- internal helpers ---------
    def _run_doc_parser(self, input_path: Path, save_dir: Path) -> Tuple[str, Dict[int, str]]:
        """
        调用 `paddleocr doc_parser`，收集 save_dir 下的所有 .md 合并。
        """
        save_dir.mkdir(parents=True, exist_ok=True)

        cmd = f"""
        paddleocr doc_parser \
          --input {shlex.quote(str(input_path))} \
          --save_path {shlex.quote(str(save_dir))} \
          --vl_rec_backend {self.backend} \
          --vl_rec_server_url {shlex.quote(self.server_url)} \
          --vl_rec_model_name {shlex.quote(self.model_name)}
        """
        # 规整空白
        cmd = " ".join(cmd.split())
        self._log.info(f"[doc_parser] {cmd}")

        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = res.stdout.decode(errors="ignore")
        if res.returncode != 0:
            self._log.error(f"[doc_parser] 失败 rc={res.returncode}\n{out}")
            raise OcrError("paddleocr doc_parser 调用失败")
        self._log.info(f"[doc_parser] 完成。日志片段：\n{out[:800]}")

        # 收集 md（有的版本会放到子目录）
        md_files = sorted(save_dir.glob("*.md")) or sorted(save_dir.rglob("*.md"))
        if not md_files:
            raise OcrError("doc_parser 未生成 .md 文件")

        merged_md = ""
        page_map: Dict[int, str] = {}
        for i, md in enumerate(md_files, start=1):
            txt = md.read_text(encoding="utf-8", errors="ignore")
            # 去图片标记，减少 tokens
            txt = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", txt)
            # 合并
            merged_md += (self.page_break_text if merged_md else "") + txt.strip()
            page_map[i] = txt

        return merged_md, page_map

    def _postprocess_outputs(self, save_dir: Path) -> None:
        """
        按 save_mode / save_images / save_layout_png 清理输出目录，减少 IO 占用。
        - none:  不保留任何文件（此函数会在 ocr_files 调用后被上层删除 tempdir，这里无需处理）
        - md:    仅保留 .md
        - json:  仅保留 *_res.json
        - all:   全部保留，但可按开关剔除 PNG/JPG
        """
        if not save_dir.exists():
            return

        if self.save_mode == "none":
            # 上层用 TemporaryDirectory，外层会 cleanup，这里兜底
            try:
                shutil.rmtree(save_dir, ignore_errors=True)
            except Exception:
                pass
            return

        # 想要保留的扩展名
        keep_exts: set[str] = set()
        if self.save_mode == "md":
            keep_exts = {".md"}
        elif self.save_mode == "json":
            # 只保留 *_res.json（其余 json 删除）
            keep_exts = {".json"}
        elif self.save_mode == "all":
            # 全部保留，但后面会根据开关剔除图片
            keep_exts = set()

        # 1) 遍历删除不想要的文件类型
        for p in save_dir.rglob("*"):
            if not p.is_file():
                continue
            suffix = p.suffix.lower()

            # 只保留 md/json 时的通用剔除
            if self.save_mode in {"md", "json"}:
                if suffix not in keep_exts:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue

                # json 模式下，仅保留 *_res.json
                if self.save_mode == "json" and suffix == ".json":
                    if not p.name.endswith("_res.json"):
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass
                    continue

            # all 模式：稍后处理图片剔除
            # md/json 模式走到这里说明当前文件是保留对象（上面已删掉其它）

        # 2) 处理图片剔除（对 all / json / md 都生效）
        #    - save_images=False 时，删除普通页图（.png/.jpg）
        #    - save_layout_png=False 时，删除 layout 可视化 PNG（命名包含 "_layout_"）
        for p in list(save_dir.rglob("*")):
            if not p.is_file():
                continue
            name = p.name.lower()
            suffix = p.suffix.lower()

            # 常见图片
            if suffix in {".png", ".jpg", ".jpeg"}:
                # layout 可视化
                if ("_layout_" in name or "layout_det_res" in name or "layout_order_res" in name):
                    if not self.save_layout_png:
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass
                else:
                    # 普通页图
                    if not self.save_images:
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass

        # 3) 清理空目录
        for d in sorted(save_dir.rglob("*"), key=lambda x: len(str(x)), reverse=True):
            if d.is_dir():
                try:
                    next(d.iterdir())
                except StopIteration:
                    # 空目录
                    try:
                        d.rmdir()
                    except Exception:
                        pass

    def _get_duplicate_lines(
        self, lines: List[str], most_common: int, min_length: int, min_count: int
    ) -> List[str]:
        cnt = Counter([ln for ln in lines if ln.strip()])
        dups = [
            ln for ln, c in cnt.most_common(most_common)
            if len(ln) >= min_length and c >= min_count and ln.strip() != self.page_break_text.strip()
        ]
        return dups
