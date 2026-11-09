"""Air-gapped local OCR execution, line phrase grouping, and spatial IoU deduplication."""

from __future__ import annotations

import concurrent.futures
import difflib
import functools
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import OCREngineUnavailableError, ScanConfig
from .models import DetectedRegion, PassImage

logger = logging.getLogger("pixel_guard.ocr_engine")

_ALNUM_RE = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class _WordToken:
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float
    block_num: int
    par_num: int
    line_num: int


def resolve_tesseract_binary(config: ScanConfig) -> str | None:
    """Locate the local tesseract executable via config or system PATH."""
    if config.tesseract_cmd:
        candidate = Path(config.tesseract_cmd)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(config.tesseract_cmd)
        if found:
            return found
        return None
    return shutil.which("tesseract")


def _parse_tesseract_tsv(tsv_text: str, min_conf: float) -> list[_WordToken]:
    """Parse standard Tesseract TSV output into filtered word tokens."""
    tokens: list[_WordToken] = []
    lines = tsv_text.splitlines()
    if len(lines) <= 1:
        return tokens

    for row in lines[1:]:
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        try:
            level = int(cols[0])
            if level != 5:
                continue
            conf_raw = float(cols[10])
            if conf_raw < 0:
                continue
            conf = conf_raw / 100.0
            word = cols[11].strip()
            if not word or conf < min_conf:
                continue
            if not _ALNUM_RE.search(word):
                continue
            x = int(cols[6])
            y = int(cols[7])
            w = int(cols[8])
            h = int(cols[9])
            if w <= 0 or h <= 0:
                continue
            tokens.append(
                _WordToken(
                    text=word,
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    conf=conf,
                    block_num=int(cols[2]),
                    par_num=int(cols[3]),
                    line_num=int(cols[4]),
                )
            )
        except ValueError:
            continue
    return tokens


def _run_tesseract_on_array(
    image: np.ndarray,
    psm: int,
    tesseract_bin: str,
    min_conf: float,
    timeout_s: float = 10.0,
) -> list[_WordToken]:
    """Execute local Tesseract OCR on a single grayscale uint8 array with bounded OpenMP threads."""
    tess_env = os.environ.copy()
    tess_env["OMP_THREAD_LIMIT"] = "2" if (image.shape[0] * image.shape[1]) >= 600_000 else "1"
    with tempfile.NamedTemporaryFile(suffix=".pgm", delete=True) as tmp:
        cv2.imwrite(tmp.name, image)
        try:
            proc = subprocess.run(
                [tesseract_bin, tmp.name, "stdout", "--oem", "3", "--psm", str(psm), "tsv"],
                env=tess_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Tesseract OCR timed out after %.1fs on psm=%d (%s)", timeout_s, psm, image.shape)
            return []
        if proc.returncode != 0:
            return []
        return _parse_tesseract_tsv(proc.stdout, min_conf=min_conf)


def _group_tokens_into_lines(tokens: list[_WordToken]) -> list[tuple[str, tuple[int, int, int, int], float]]:
    """Merge horizontally adjacent words on the same Tesseract line into phrase boxes."""
    if not tokens:
        return []

    buckets: dict[tuple[int, int, int], list[_WordToken]] = {}
    for tok in tokens:
        key = (tok.block_num, tok.par_num, tok.line_num)
        buckets.setdefault(key, []).append(tok)

    merged_lines: list[tuple[str, tuple[int, int, int, int], float]] = []
    for line_tokens in buckets.values():
        ordered = sorted(line_tokens, key=lambda t: t.x)
        # Split into separate segments if a huge horizontal gap (> 4x line height) separates columns
        segments: list[list[_WordToken]] = [[ordered[0]]]
        for tok in ordered[1:]:
            prev = segments[-1][-1]
            prev_right = prev.x + prev.w
            max_gap = max(60, int(max(prev.h, tok.h) * 4.0))
            if tok.x - prev_right > max_gap:
                segments.append([tok])
            else:
                segments[-1].append(tok)

        for seg in segments:
            phrase = " ".join(t.text for t in seg).strip()
            if len(phrase) < 2:
                continue
            x0 = min(t.x for t in seg)
            y0 = min(t.y for t in seg)
            x1 = max(t.x + t.w for t in seg)
            y1 = max(t.y + t.h for t in seg)
            mean_conf = float(sum(t.conf for t in seg) / len(seg))
            merged_lines.append((phrase, (x0, y0, x1 - x0, y1 - y0), mean_conf))

    return merged_lines


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Compute spatial Intersection-over-Union (IoU) between two (x, y, w, h) boxes."""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    inter = float((ix2 - ix1) * (iy2 - iy1))
    union = float(aw * ah + bw * bh) - inter
    return inter / union if union > 0 else 0.0


def _vertical_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Fraction of the shorter box's vertical span overlapped by the other box."""
    ay1, ah = a[1], a[3]
    by1, bh = b[1], b[3]
    iy1 = max(ay1, by1)
    iy2 = min(ay1 + ah, by1 + bh)
    if iy2 <= iy1:
        return 0.0
    return float(iy2 - iy1) / float(max(1, min(ah, bh)))


def _horizontal_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Fraction of the narrower box's horizontal span overlapped by the other box."""
    ax1, aw = a[0], a[2]
    bx1, bw = b[0], b[2]
    ix1 = max(ax1, bx1)
    ix2 = min(ax1 + aw, bx1 + bw)
    if ix2 <= ix1:
        return 0.0
    return float(ix2 - ix1) / float(max(1, min(aw, bw)))


@functools.lru_cache(maxsize=4096)
def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _candidate_containment_ratio(container: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> float:
    """Fraction of 'inner' bounding box area covered by 'container'."""
    ax1, ay1, aw, ah = container
    bx1, by1, bw, bh = inner
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return float((ix2 - ix1) * (iy2 - iy1)) / float(max(1, bw * bh))


def _is_duplicate_region(existing: DetectedRegion, candidate: DetectedRegion) -> bool:
    """Determine if two regions represent the same underlying visual text line."""
    if existing.frame_index != candidate.frame_index:
        return False

    ay1, ah = existing.bbox[1], existing.bbox[3]
    by1, bh = candidate.bbox[1], candidate.bbox[3]
    if ay1 > by1 + bh + 6 or by1 > ay1 + ah + 6:
        return False

    iou = _bbox_iou(existing.bbox, candidate.bbox)
    if iou >= 0.55:
        return True

    # If existing was cleanly read in Pass A ('baseline') and covers >=65% of an enhanced-pass fragment
    if (
        existing.origin_pass == "baseline"
        and candidate.origin_pass not in {"baseline", "alpha_zero_rgb", "micro_upscale"}
        and _candidate_containment_ratio(existing.bbox, candidate.bbox) >= 0.65
    ):
        return True

    v_ov = _vertical_overlap_ratio(existing.bbox, candidate.bbox)
    h_ov = _horizontal_overlap_ratio(existing.bbox, candidate.bbox)
    if v_ov >= 0.55 and h_ov >= 0.50:
        norm_a = _normalize_text(existing.text)
        norm_b = _normalize_text(candidate.text)
        if not norm_a or not norm_b:
            return False
        if norm_a in norm_b or norm_b in norm_a:
            return True
        ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
        if ratio >= 0.72:
            return True
    return False


def _ocr_single_pass(
    pass_item: PassImage,
    tesseract_bin: str,
    min_conf: float,
    native_dims: tuple[int, int],
    timeout_s: float = 10.0,
) -> list[DetectedRegion]:
    """Worker routine running configured PSM modes on one PassImage and mapping coords to 1x."""
    img_w, img_h = native_dims
    pass_regions: list[DetectedRegion] = []

    for psm in pass_item.psm_modes:
        tokens = _run_tesseract_on_array(
            pass_item.image,
            psm=psm,
            tesseract_bin=tesseract_bin,
            min_conf=min_conf,
            timeout_s=timeout_s,
        )
        lines = _group_tokens_into_lines(tokens)
        for phrase, (px, py, pw, ph), conf in lines:
            scale = pass_item.scale_factor
            nx = max(0, min(img_w - 1, int(round(px / scale)) + pass_item.offset_x))
            ny = max(0, min(img_h - 1, int(round(py / scale)) + pass_item.offset_y))
            nw = max(1, min(img_w - nx, int(round(pw / scale))))
            nh = max(1, min(img_h - ny, int(round(ph / scale))))

            # Store cropped pass image for polarity-guided stroke mask segmentation
            ph_img, pw_img = pass_item.image.shape[:2]
            cx0 = max(0, px - 4)
            cy0 = max(0, py - 4)
            cx1 = min(pw_img, px + pw + 4)
            cy1 = min(ph_img, py + ph + 4)
            crop = pass_item.image[cy0:cy1, cx0:cx1].copy()

            candidate = DetectedRegion(
                text=phrase,
                bbox=(nx, ny, nw, nh),
                confidence=conf,
                origin_pass=pass_item.pass_id,
                display_method=pass_item.display_label,
                frame_index=pass_item.frame_index,
                pass_crop_gray=crop,
            )
            if not any(_is_duplicate_region(r, candidate) for r in pass_regions):
                pass_regions.append(candidate)

        # Skip redundant sparse PSM 11 when primary PSM 6 already recovered structured lines
        if psm == 6 and (
            len(pass_regions) >= 2
            or (len(pass_regions) == 1 and pass_regions[0].confidence >= 0.55)
        ):
            break

    return pass_regions


def _run_easyocr_fallback(
    passes: list[PassImage],
    native_dims: tuple[int, int],
    min_conf: float,
) -> list[list[DetectedRegion]]:
    """Optional offline EasyOCR fallback when Tesseract binary is unavailable."""
    try:
        import easyocr  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OCREngineUnavailableError(
            "Local OCR engine unavailable: 'tesseract' binary was not found on PATH "
            "(and PIXEL_GUARD_TESSERACT_CMD is unset), and optional fallback 'easyocr' is not installed."
        ) from exc

    reader = easyocr.Reader(["en"], gpu=False, download_enabled=False, verbose=False)
    img_w, img_h = native_dims
    all_results: list[list[DetectedRegion]] = []

    for pass_item in passes:
        raw_hits = reader.readtext(pass_item.image, detail=1)
        regions: list[DetectedRegion] = []
        for pts, text, conf in raw_hits:
            if float(conf) < min_conf or not _ALNUM_RE.search(str(text)):
                continue
            xs = [int(p[0]) for p in pts]
            ys = [int(p[1]) for p in pts]
            px, py = min(xs), min(ys)
            pw, ph = max(1, max(xs) - px), max(1, max(ys) - py)
            scale = pass_item.scale_factor
            nx = max(0, min(img_w - 1, int(round(px / scale)) + pass_item.offset_x))
            ny = max(0, min(img_h - 1, int(round(py / scale)) + pass_item.offset_y))
            nw = max(1, min(img_w - nx, int(round(pw / scale))))
            nh = max(1, min(img_h - ny, int(round(ph / scale))))
            regions.append(
                DetectedRegion(
                    text=str(text).strip(),
                    bbox=(nx, ny, nw, nh),
                    confidence=float(conf),
                    origin_pass=pass_item.pass_id,
                    display_method=pass_item.display_label,
                    frame_index=pass_item.frame_index,
                )
            )
        all_results.append(regions)
    return all_results


def run_multipass_ocr(
    passes: list[PassImage],
    native_dims: tuple[int, int],
    config: ScanConfig,
    frame_dims: dict[int, tuple[int, int]] | None = None,
) -> list[DetectedRegion]:
    """Execute air-gapped OCR concurrently across passes and deduplicate spatially per page/frame."""
    if not passes:
        return []

    dims_map = frame_dims or {}
    tesseract_bin = resolve_tesseract_binary(config)
    if config.ocr_backend == "easyocr" or tesseract_bin is None:
        per_pass_lists = _run_easyocr_fallback(passes, native_dims, config.ocr_min_confidence)
    else:
        max_workers = min(config.ocr_workers, len(passes))
        if max_workers <= 1:
            per_pass_lists = [
                _ocr_single_pass(
                    p,
                    tesseract_bin,
                    config.ocr_min_confidence,
                    dims_map.get(p.frame_index, native_dims),
                    config.ocr_pass_timeout_s,
                )
                for p in passes
            ]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [
                    pool.submit(
                        _ocr_single_pass,
                        p,
                        tesseract_bin,
                        config.ocr_min_confidence,
                        dims_map.get(p.frame_index, native_dims),
                        config.ocr_pass_timeout_s,
                    )
                    for p in passes
                ]
                per_pass_lists = [f.result() for f in futures]

    # Priority order ensures Pass A ('baseline') retains ownership whenever it read the text
    pass_priority = {
        "baseline": 0,
        "clahe_contrast": 1,
        "alpha_partial": 2,
        "alpha_zero_rgb": 3,
        "micro_upscale": 4,
        "perceptual_chroma": 5,
        "edge_frequency": 6,
    }
    ordered_pairs = sorted(
        zip(passes, per_pass_lists),
        key=lambda pair: (pair[0].frame_index, pass_priority.get(pair[0].pass_id, 99)),
    )

    deduplicated: list[DetectedRegion] = []
    for _, region_list in ordered_pairs:
        for candidate in region_list:
            matched_idx: int | None = None
            for idx, existing in enumerate(deduplicated):
                if _is_duplicate_region(existing, candidate):
                    matched_idx = idx
                    break

            if matched_idx is None:
                deduplicated.append(candidate)
            else:
                existing = deduplicated[matched_idx]
                # Keep baseline origin; if both non-baseline and candidate recovered a much fuller phrase, upgrade text
                if existing.origin_pass != "baseline" and len(candidate.text) > len(existing.text) + 6 and candidate.confidence >= existing.confidence:
                    deduplicated[matched_idx] = candidate

    # Sort top-to-bottom, left-to-right per frame for natural reading order
    deduplicated.sort(key=lambda r: (r.frame_index, r.bbox[1] // 10, r.bbox[0]))
    return deduplicated
