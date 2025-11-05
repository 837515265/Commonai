# module/seal.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Tuple
import json
import re

import fitz  # PyMuPDF
from PIL import Image
from paddlex import create_pipeline


BANK_KEYWORDS = [
    "银行", "商业银行", "农村商业银行", "信用社", "农信", "农商行", "农联社", "农村信用合作社"
]

BANK_NAME_REGEXES = [
    # 优先抽更完整的“XX银行股份有限公司”“XX农村商业银行”等
    r"([^\s，。、“”]+银行股份有限公司)",
    r"([^\s，。、“”]+农村商业银行)",
    r"([^\s，。、“”]+商业银行)",
    r"([^\s，。、“”]+银行)",
    r"([^\s，。、“”]+信用合作社)",
    r"([^\s，。、“”]+信用社)",
]

def _jsonable(res: Any) -> Dict[str, Any]:
    try:
        if hasattr(res, "to_dict"):
            return res.to_dict()
    except Exception:
        pass
    try:
        return json.loads(json.dumps(res, default=lambda o: getattr(o, "__dict__", str(o))))
    except Exception:
        return {"_repr": str(res)}

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _is_bank_text(s: str) -> bool:
    return s and any(k in s for k in BANK_KEYWORDS)

def _score_bank_name(s: str) -> float:
    """简单的打分：长度 + 关键词命中数 + 正则命中加权"""
    if not s:
        return 0.0
    base = len(s) * 0.5
    kw = sum(1 for k in BANK_KEYWORDS if k in s) * 2.0
    rx = 0.0
    for pat in BANK_NAME_REGEXES:
        if re.search(pat, s):
            rx += 3.0
    return base + kw + rx

def _extract_bank_name_candidates(text: str) -> List[Tuple[str, float]]:
    text = (text or "").strip()
    cands: List[str] = []
    for pat in BANK_NAME_REGEXES:
        for m in re.finditer(pat, text):
            cands.append(m.group(1))
    # 如果正则一个都没抓到，退化：整段里带“银行/信用社”的也算候选
    if not cands and _is_bank_text(text):
        cands.append(text)
    scored = [(t, _score_bank_name(t)) for t in cands]
    # 去重保留最高分
    best: Dict[str, float] = {}
    for t, sc in scored:
        best[t] = max(best.get(t, 0.0), sc)
    return sorted(best.items(), key=lambda x: -x[1])

def _render_pdf_page(pdf: Path, page_index: int, w: int, h: int) -> Image.Image:
    """把 PDF 第 page_index(0-based) 页按像素 w*h 渲干净底图"""
    doc = fitz.open(pdf.as_posix())
    try:
        page = doc[page_index]
        mx = w / page.rect.width
        my = h / page.rect.height
        pm = page.get_pixmap(matrix=fitz.Matrix(mx, my), alpha=False)
        return Image.frombytes("RGB", [pm.width, pm.height], pm.samples)
    finally:
        doc.close()

def _crop(img: Image.Image, bbox: List[float], margin: int) -> Image.Image:
    W, H = img.size
    x1, y1, x2, y2 = bbox
    cx1 = max(0, int(round(x1)) - margin)
    cy1 = max(0, int(round(y1)) - margin)
    cx2 = min(W, int(round(x2)) + margin)
    cy2 = min(H, int(round(y2)) + margin)
    return img.crop((cx1, cy1, cx2, cy2))


class SealTool:
    """最小依赖：PaddleX layout_parsing 只开 seal；从 layout/文本/专用 seal_ocr 三路拿信息；裁图用原始底图"""

    def __init__(self, margin: int = 8):
        self.pipeline = create_pipeline("Seal.yaml")
        self.margin = margin

    def _extract_page_info(self, res_dict: Dict[str, Any]) -> Dict[str, Any]:
        # layout seal框
        seal_boxes = []
        layout = res_dict.get("layout_det_res") or {}
        for it in (layout.get("boxes") or []):
            if str(it.get("label", "")).lower() == "seal":
                coord = it.get("coordinate", [])
                sc = float(it.get("score", 0.0))
                if isinstance(coord, list) and len(coord) == 4:
                    x1, y1, x2, y2 = coord
                    seal_boxes.append({"bbox": [float(x1), float(y1), float(x2), float(y2)], "score": sc})

        # parsing_res_list 的 seal 文本块
        seal_blocks = []
        for blk in (res_dict.get("parsing_res_list") or []):
            if str(blk.get("block_label", "")).lower() == "seal":
                bbox = blk.get("block_bbox", [])
                txt  = (blk.get("block_content") or "").strip()
                if isinstance(bbox, list) and len(bbox) == 4:
                    seal_blocks.append({"bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                                        "text": txt})

        # seal_res_list 里的 OCR 文本（常常是圆环字+专用章）
        seal_texts = []
        for seg in (res_dict.get("seal_res_list") or []):
            for t in (seg.get("rec_texts") or []):
                t = str(t).strip()
                if t:
                    seal_texts.append(t)

        return {
            "seal_boxes_layout": seal_boxes,
            "seal_blocks_text": seal_blocks,
            "seal_ocr_texts": seal_texts,
        }

    def extract_from_file(self, input_path: Path, out_dir: Path | None = None) -> Dict[str, Any]:
        """
        返回：
        {
          "best_bank": "山东恒农村商业银行股份有限公司",
          "bank_seals": [ {page_index, text, bbox, image}, ... ],
          "pages": {...}  # 每页明细，必要时可用
        }
        """
        input_path = Path(input_path).resolve()
        if out_dir:
            out_dir = Path(out_dir).resolve()
            _ensure_dir(out_dir)
            _ensure_dir(out_dir / "img")
            _ensure_dir(out_dir / "json")
            _ensure_dir(out_dir / "bank_seals")
            _ensure_dir(out_dir / "raw_pages_cache")

        # 只开 seal，避免“参数非法”情况
        outputs = self.pipeline.predict(
            input_path.as_posix(),
            use_seal_recognition=True,
        )

        pages: Dict[str, Any] = {}
        bank_items: List[Dict[str, Any]] = []
        global_candidates: Dict[str, float] = {}

        stem = input_path.stem
        for idx, res in enumerate(outputs, 1):
            # 保存原始可视化与json（可选）
            if out_dir:
                res.save_to_img((out_dir / "img").as_posix())
                res.save_to_json((out_dir / "json").as_posix())

            res_d = _jsonable(res)
            page_idx = int(res_d.get("page_index") if res_d.get("page_index") is not None else idx)
            info = self._extract_page_info(res_d)
            pages[str(page_idx)] = info

            # 按 parsing_res 的 seal 文本块来裁剪（位置稳定）
            bank_blocks = [b for b in info["seal_blocks_text"] if _is_bank_text(b.get("text", ""))]

            # 渲底图并裁切
            layout_png = (out_dir / "img" / f"{stem}_{page_idx}_layout_det_res.png") if out_dir else None
            if layout_png and layout_png.exists():
                W, H = Image.open(layout_png).size
            else:
                with fitz.open(input_path.as_posix()) as tmpdoc:
                    pg = tmpdoc[page_idx]
                    pm = pg.get_pixmap(matrix=fitz.Matrix(220/72.0, 220/72.0), alpha=False)
                    W, H = pm.width, pm.height
            raw_cache = (out_dir / "raw_pages_cache" / f"{stem}_{page_idx}_raw.png") if out_dir else None
            if raw_cache and not raw_cache.exists():
                img = _render_pdf_page(input_path, page_idx, W, H)
                img.save(raw_cache.as_posix())
            raw_img = Image.open(raw_cache).convert("RGB") if raw_cache and raw_cache.exists() else None

            for i, b in enumerate(bank_blocks, 1):
                text = b.get("text", "")
                bbox = b.get("bbox", [])
                img_path = ""
                if raw_img is not None and bbox:
                    roi = _crop(raw_img, bbox, self.margin)
                    out_p = (out_dir / "bank_seals" / f"p{page_idx:03d}_bank_{i:02d}.png") if out_dir else None
                    if out_p:
                        roi.save(out_p.as_posix())
                        img_path = out_p.as_posix()

                # 文本→候选银行名
                for t, sc in _extract_bank_name_candidates(text):
                    global_candidates[t] = max(global_candidates.get(t, 0.0), sc)

                bank_items.append({
                    "page_index": page_idx,
                    "text": text,
                    "bbox": bbox,
                    "image": img_path
                })

            # 兜底：seal_ocr_texts 里也跑一遍候选
            joined = "，".join(info["seal_ocr_texts"])
            for t, sc in _extract_bank_name_candidates(joined):
                global_candidates[t] = max(global_candidates.get(t, 0.0), sc)

        sorted_cands = sorted(global_candidates.items(), key=lambda x: -x[1])
        best_bank = sorted_cands[0][0] if sorted_cands else ""

        return {
            "best_bank": best_bank,
            "bank_seals": bank_items,
            "pages": pages,
        }
