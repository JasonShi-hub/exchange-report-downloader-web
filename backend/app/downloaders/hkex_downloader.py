#!/usr/bin/env python3
"""
香港联合交易所(HKEX)上市公司公告自动下载
使用 HKEX 当前对外接口:
- 股票搜索: /search/prefix.do /search/partial.do
- 公告查询: /search/titleSearchServlet.do
"""

import html
import hashlib
import json
import os
import re
import sys
import time
import random
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    sys.exit(1)


# ============================================================
# 常量与配置
# ============================================================

HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_SEARCH_API_URL = f"{HKEX_BASE_URL}/search/titleSearchServlet.do"
HKEX_STOCK_PREFIX_URL = f"{HKEX_BASE_URL}/search/prefix.do"
HKEX_STOCK_PARTIAL_URL = f"{HKEX_BASE_URL}/search/partial.do"

HKEX_INITIAL_ROW_RANGE = 100
HKEX_MAX_ROW_RANGE = 3000

HKEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Referer": f"{HKEX_BASE_URL}/search/titlesearch.xhtml",
}

# 港股公告类别映射 (2026-02 实测 HKEX 当前代码)
# search_type: 0=ALL, 1=Headline Category, 2=Document Type(历史)
HKEX_CATEGORY_MAP = {
    "年度业绩": {
        "search_type": "1", "t1": "10000", "t2g": "3", "t2": "13300"
    },
    "中期业绩": {
        "search_type": "1", "t1": "10000", "t2g": "3", "t2": "13400"
    },
    "季度业绩": {
        "search_type": "1", "t1": "10000", "t2g": "3", "t2": "13600"
    },
    "年度报告": {
        "search_type": "1", "t1": "40000", "t2g": "-1", "t2": "40100"
    },
    "公告及通知": {
        "search_type": "1", "t1": "10000", "t2g": "-2", "t2": "-2"
    },
    "主要交易": {
        "search_type": "1", "t1": "10000", "t2g": "6", "t2": "16300"
    },
    "须予披露交易": {
        "search_type": "1", "t1": "10000", "t2g": "6", "t2": "16200"
    },
    "关连交易": {
        "search_type": "1", "t1": "10000", "t2g": "1", "t2": "11200"
    },
    "股权变动": {
        "search_type": "1", "t1": "10000", "t2g": "7", "t2": "17200"
    },
    "供股": {
        "search_type": "1", "t1": "10000", "t2g": "8", "t2": "18500"
    },
    "配售": {
        "search_type": "1", "t1": "10000", "t2g": "8", "t2": "18480"
    },
    "通函": {
        "search_type": "1", "t1": "20000", "t2g": "-2", "t2": "-2"
    },
    "翌日披露": {
        "search_type": "1", "t1": "50000", "t2g": "-2", "t2": "-2"
    },
    "月报表": {
        "search_type": "1", "t1": "51500", "t2g": "-2", "t2": "-2"
    },
}

HKEX_ALL_CATEGORY_QUERY = {
    "search_type": "0", "t1": "-2", "t2g": "-2", "t2": "-2"
}


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 180:
        name = name[:180]
    return name


def extract_year(date_str: str) -> str:
    """从日期字符串提取年份"""
    m = re.search(r'(\d{4})', date_str or "")
    return m.group(1) if m else "未知年份"


def detect_language(url: str) -> str:
    """根据URL中的 _c / _e 后缀判断语言"""
    lower = (url or "").lower()
    if re.search(r'_c(\.|_|$)', lower, re.IGNORECASE):
        return "中文"
    if re.search(r'_e(\.|_|$)', lower, re.IGNORECASE):
        return "英文"
    return "未知"


def clean_text(text: str) -> str:
    """解码 HTML 实体并移除标签/多余空白"""
    if not text:
        return ""
    s = html.unescape(str(text))
    s = re.sub(r'(?i)<br\s*/?>', ' ', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def build_short_doc_key(news_id: str, url: str) -> str:
    """生成短且稳定的文档唯一键，避免文件名冲突。"""
    nid = re.sub(r'\D', '', str(news_id or ""))
    if nid:
        return f"N{nid[-10:]}"
    digest = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:8]
    return f"H{digest}"


def build_output_filename(ann_date: str, title: str, lang: str, news_id: str, url: str) -> str:
    """构建输出文件名：日期_标题_语言_短唯一键.pdf"""
    lang_suffix = f"_{lang}" if lang in ("中文", "英文") else ""
    base = sanitize_filename(f"{ann_date}_{title}{lang_suffix}")
    doc_key = build_short_doc_key(news_id, url)

    # 留出唯一键和扩展名长度，避免标题截断后丢失唯一键
    reserve = len(doc_key) + len("_.pdf")
    max_base_len = max(20, 180 - reserve)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()

    return f"{base}_{doc_key}.pdf"


# ============================================================
# 核心类
# ============================================================

class HKEXDownloader:
    def __init__(self, output_dir: str, delay_range: tuple = (1.5, 3.5),
                 max_retries: int = 3, on_message=None):
        self.output_dir = output_dir
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.on_message = on_message or (lambda msg, **kw: print(msg))
        self.stop_requested = False
        self.stats = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}

        self.session = requests.Session()
        self.session.headers.update(HKEX_HEADERS)
        try:
            self.session.get(HKEX_BASE_URL, timeout=15)
        except requests.RequestException:
            pass

    def _delay(self):
        """随机延迟，可被 stop_requested 中断"""
        remaining = random.uniform(*self.delay_range)
        while remaining > 0 and not self.stop_requested:
            step = min(remaining, 0.3)
            time.sleep(step)
            remaining -= step

    def _emit(self, msg, **kwargs):
        self.on_message(msg, **kwargs)

    @staticmethod
    def _digits_only(value: str) -> str:
        return re.sub(r'\D', '', value or "")

    @staticmethod
    def _normalize_input_code(stock_code: str) -> str:
        digits = re.sub(r'\D', '', stock_code or "")
        if digits:
            return digits.zfill(4)
        return (stock_code or "").strip()

    @staticmethod
    def _strip_leading_zeros(code: str) -> str:
        digits = re.sub(r'\D', '', code or "")
        if not digits:
            return ""
        return digits.lstrip('0') or "0"

    def _code_matches(self, user_code: str, hkex_code: str) -> bool:
        left = self._strip_leading_zeros(user_code)
        right = self._strip_leading_zeros(hkex_code)
        return bool(left) and left == right

    @staticmethod
    def _parse_jsonp(payload: str) -> dict:
        text = (payload or "").strip()
        m = re.match(r'^[^(]*\((.*)\)\s*;?\s*$', text, re.S)
        if m:
            text = m.group(1)
        return json.loads(text)

    def _fetch_stock_candidates(self, keyword: str) -> list:
        """通过 prefix/partial 接口查询股票候选项"""
        if not keyword:
            return []

        endpoints = [HKEX_STOCK_PREFIX_URL, HKEX_STOCK_PARTIAL_URL]
        sec_types = ["A", "I"]  # Current + Delisted

        candidates = []
        seen = set()

        for sec_type in sec_types:
            for endpoint in endpoints:
                if self.stop_requested:
                    return candidates

                params = {
                    "lang": "EN",
                    "type": sec_type,
                    "name": keyword,
                    "market": "SEHK",
                    "callback": "callback",
                }

                try:
                    resp = self.session.get(endpoint, params=params, timeout=20)
                    resp.raise_for_status()
                    data = self._parse_jsonp(resp.text)
                    for item in data.get("stockInfo", []) or []:
                        stock_id = item.get("stockId")
                        code = str(item.get("code") or "").strip()
                        name = clean_text(item.get("name") or "")
                        if stock_id in (None, "") or not code:
                            continue

                        key = str(stock_id)
                        if key in seen:
                            continue
                        seen.add(key)

                        candidates.append({
                            "stock_id": str(stock_id),
                            "code": code,
                            "name": name or code,
                        })
                except (requests.RequestException, ValueError, json.JSONDecodeError):
                    continue

        return candidates

    def lookup_stock_info(self, stock_code: str) -> Optional[dict]:
        """查询股票代码，返回 {"code", "name", "stock_id"} 或 None"""
        normalized = self._normalize_input_code(stock_code)
        digits = self._digits_only(normalized)

        keywords = []
        if digits:
            keywords.extend([
                digits.zfill(4),
                digits.zfill(5),
                digits.lstrip("0") or "0",
            ])
        else:
            keywords.append(normalized)

        # 去重保序
        seen_kw = set()
        keywords = [k for k in keywords if k and not (k in seen_kw or seen_kw.add(k))]

        for attempt in range(1, self.max_retries + 1):
            if self.stop_requested:
                return None

            try:
                merged = []
                seen_id = set()

                for kw in keywords:
                    for item in self._fetch_stock_candidates(kw):
                        sid = item["stock_id"]
                        if sid in seen_id:
                            continue
                        seen_id.add(sid)
                        merged.append(item)

                if not merged:
                    if attempt < self.max_retries:
                        self._emit(f"  [重试 {attempt}/{self.max_retries}] 未匹配到港股代码 {normalized}")
                        self._delay()
                    continue

                exact = [x for x in merged if self._code_matches(normalized, x["code"])]
                chosen = exact[0] if exact else merged[0]

                code = chosen["code"]
                if code.isdigit() and len(code) < 4:
                    code = code.zfill(4)

                return {
                    "code": code,
                    "name": chosen["name"],
                    "stock_id": chosen["stock_id"],
                }
            except Exception as e:
                self._emit(f"  [重试 {attempt}/{self.max_retries}] 验证股票失败: {e}")
                if attempt < self.max_retries:
                    self._delay()

        return None

    @staticmethod
    def _to_api_date(date_str: str) -> str:
        """将输入日期转换为 YYYYMMDD"""
        raw = (date_str or "").strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y%m%d")
            except ValueError:
                continue
        digits = re.sub(r'\D', '', raw)
        return digits[:8] if len(digits) >= 8 else raw

    def _search_once(self, stock_id: str, start_date: str, end_date: str,
                     query_cfg: dict, row_range: int, lang: str = "E") -> Tuple[list, bool, int]:
        params = {
            "sortDir": "1",               # 1 = 最新优先
            "sortByOptions": "DateTime",
            "category": "0",             # 0 = Current Securities
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": "-1",
            "fromDate": self._to_api_date(start_date),
            "toDate": self._to_api_date(end_date),
            "title": "",
            "searchType": query_cfg.get("search_type", "0"),
            "t1code": query_cfg.get("t1", "-2"),
            "t2Gcode": query_cfg.get("t2g", "-2"),
            "t2code": query_cfg.get("t2", "-2"),
            "rowRange": str(row_range),
            "lang": lang,
        }

        resp = self.session.get(HKEX_SEARCH_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        raw_result = data.get("result", "[]")
        if isinstance(raw_result, str):
            rows = json.loads(raw_result) if raw_result.strip() else []
        elif isinstance(raw_result, list):
            rows = raw_result
        else:
            rows = []

        has_next = bool(data.get("hasNextRow"))
        record_cnt = int(data.get("recordCnt") or len(rows) or 0)
        return rows, has_next, record_cnt

    @staticmethod
    def _normalize_result_date(raw: str) -> str:
        """将 HKEX 返回日期统一为 YYYY-MM-DD"""
        text = (raw or "").strip()

        m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if m:
            day, month, year = m.group(1), m.group(2), m.group(3)
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)
        if m:
            year, month, day = m.group(1), m.group(2), m.group(3)
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        return text

    def _convert_row(self, row: dict, cat_name: str, fallback_lang: str = "未知") -> Optional[dict]:
        file_link = (row.get("FILE_LINK") or "").strip()
        if not file_link:
            file_link = (row.get("DOD_WEB_PATH") or "").strip()
        if not file_link:
            return None

        full_url = file_link if file_link.startswith("http") else urljoin(HKEX_BASE_URL, file_link)

        title = clean_text(row.get("TITLE") or row.get("SHORT_TEXT") or os.path.basename(file_link))
        date_str = self._normalize_result_date(row.get("DATE_TIME") or "")
        lang = detect_language(full_url)
        if lang == "未知" and fallback_lang in {"中文", "英文"}:
            lang = fallback_lang

        return {
            "title": title,
            "date": date_str,
            "url": full_url,
            "lang": lang,
            "category": cat_name,
            "news_id": str(row.get("NEWS_ID") or ""),
        }

    def _search_category(self, stock_id: str, start_date: str, end_date: str,
                         cat_name: str, query_cfg: dict,
                         api_lang: str = "E", doc_lang_label: str = "未知") -> list:
        """查询单个类别，按 rowRange 递增拉取完整结果"""
        final_rows = []
        row_range = HKEX_INITIAL_ROW_RANGE
        last_count = -1

        while True:
            if self.stop_requested:
                break

            try:
                rows, has_next, record_cnt = self._search_once(
                    stock_id=stock_id,
                    start_date=start_date,
                    end_date=end_date,
                    query_cfg=query_cfg,
                    row_range=row_range,
                    lang=api_lang,
                )
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                self._emit(f"  [错误] 查询类别 [{cat_name}] 失败: {e}")
                break

            final_rows = rows
            self._emit(f"    类别 [{cat_name}] 已获取 {len(final_rows)}/{record_cnt} 条")

            if not has_next:
                break

            if len(final_rows) <= last_count:
                self._emit(f"  [警告] 类别 [{cat_name}] 结果未增长，提前结束")
                break

            last_count = len(final_rows)
            row_range += HKEX_INITIAL_ROW_RANGE

            if row_range > HKEX_MAX_ROW_RANGE:
                self._emit(f"  [警告] 类别 [{cat_name}] 超过 {HKEX_MAX_ROW_RANGE} 条上限，已截断")
                break

            self._delay()

        items = []
        for row in final_rows:
            item = self._convert_row(row, cat_name, fallback_lang=doc_lang_label)
            if item and item["date"] and item["url"]:
                items.append(item)

        return items

    def query_announcements(self, stock_info: dict, start_date: str, end_date: str,
                            category_codes: Optional[List[str]] = None,
                            languages: Optional[List[str]] = None) -> list:
        """
        查询 HKEX 上市公司公告列表。

        Args:
            stock_info: lookup_stock_info 返回字典，含 stock_id
            start_date: 起始日期 "YYYY-MM-DD"
            end_date:   结束日期 "YYYY-MM-DD"
            category_codes: HKEX_CATEGORY_MAP 的键名列表，None 表示全部
            languages: ["中文", "英文"] 任意组合，None 表示全部

        Returns:
            [{"title": ..., "date": ..., "url": ..., "lang": ..., "category": ...}, ...]
        """
        stock_id = str(stock_info.get("stock_id") or "").strip()
        if not stock_id:
            return []

        all_results = []
        target_langs = set(languages) if languages else {"中文", "英文"}

        if category_codes:
            queries = [
                (cat, HKEX_CATEGORY_MAP[cat])
                for cat in category_codes
                if cat in HKEX_CATEGORY_MAP
            ]
        else:
            queries = [("全部", HKEX_ALL_CATEGORY_QUERY)]

        # HKEX 会按查询语言返回不同文档链接:
        # - lang=E: 英文版本(部分链接不带 _e 后缀)
        # - lang=zh: 中文版本(通常带 _c 后缀)
        if languages:
            lang_plans = []
            if "英文" in target_langs:
                lang_plans.append(("E", "英文"))
            if "中文" in target_langs:
                lang_plans.append(("zh", "中文"))
        else:
            lang_plans = [("E", "英文"), ("zh", "中文")]

        if not lang_plans:
            lang_plans = [("E", "英文")]

        for cat_name, query_cfg in queries:
            if self.stop_requested:
                break

            self._emit(f"  查询类别: {cat_name} ...")
            merged = []
            seen_urls = set()

            for api_lang, doc_lang_label in lang_plans:
                if self.stop_requested:
                    break

                self._emit(f"    使用语言源: {doc_lang_label} ({api_lang})")
                results = self._search_category(
                    stock_id=stock_id,
                    start_date=start_date,
                    end_date=end_date,
                    cat_name=cat_name,
                    query_cfg=query_cfg,
                    api_lang=api_lang,
                    doc_lang_label=doc_lang_label,
                )

                for item in results:
                    url_key = (item.get("url") or "").strip()
                    if not url_key or url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)
                    merged.append(item)

            filtered = []
            for item in merged:
                if item["lang"] in target_langs or item["lang"] == "未知":
                    filtered.append(item)

            all_results.extend(filtered)
            if merged:
                self._emit(f"  类别 [{cat_name}] 找到 {len(merged)} 条，语言过滤后 {len(filtered)} 条")

        return all_results

    def download_file(self, url: str, save_path: str) -> bool:
        """下载单个文件，支持重试，可被 stop_requested 中断"""
        for attempt in range(1, self.max_retries + 1):
            if self.stop_requested:
                return False
            try:
                resp = self.session.get(url, timeout=60, stream=True)
                resp.raise_for_status()

                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if self.stop_requested:
                            try:
                                os.remove(save_path)
                            except OSError:
                                pass
                            return False
                        f.write(chunk)
                return True
            except requests.RequestException as e:
                self._emit(f"    [重试 {attempt}/{self.max_retries}] 下载失败: {e}")
                if attempt < self.max_retries:
                    self._delay()
        return False

    def process_stock(self, stock_code: str, start_date: str, end_date: str,
                      category_codes: Optional[List[str]] = None,
                      languages: Optional[List[str]] = None):
        """处理单只港股的全部下载"""
        if self.stop_requested:
            return

        normalized_input = self._normalize_input_code(stock_code)

        self._emit(f"\n{'='*60}")
        self._emit(f"正在查询港股: {normalized_input} ({start_date} ~ {end_date})")
        self._emit(f"{'='*60}")

        stock_info = self.lookup_stock_info(normalized_input)
        if not stock_info:
            self._emit(f"  [错误] 未找到港股 {normalized_input}，请检查代码是否正确")
            return

        stock_name = stock_info.get("name", normalized_input)
        stock_display_code = stock_info.get("code", normalized_input)
        self._emit(f"  股票: {stock_name} ({stock_display_code})")

        languages_display = "、".join(languages) if languages else "全部"
        self._emit(f"  语言: {languages_display}")

        announcements = self.query_announcements(
            stock_info=stock_info,
            start_date=start_date,
            end_date=end_date,
            category_codes=category_codes,
            languages=languages,
        )

        if not announcements:
            self._emit(f"  未找到 {stock_display_code} 在指定条件下的公告")
            return

        self._emit(f"  共找到 {len(announcements)} 条公告（过滤后）")
        self.stats["total"] += len(announcements)

        stock_dir_name = sanitize_filename(f"{stock_display_code}_{stock_name}")

        for i, ann in enumerate(announcements, 1):
            if self.stop_requested:
                self._emit("  [停止] 用户取消操作")
                return

            title = ann.get("title", "未知标题")
            ann_date = ann.get("date", "")
            url = ann.get("url", "")
            lang = ann.get("lang", "未知")
            cat_name = ann.get("category", "其他")
            news_id = ann.get("news_id", "")

            if not url:
                self.stats["failed"] += 1
                continue

            year = extract_year(ann_date)
            filename = build_output_filename(ann_date, title, lang, news_id, url)
            save_dir = os.path.join(self.output_dir, stock_dir_name, cat_name, year)
            save_path = os.path.join(save_dir, filename)

            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                self._emit(f"  [{i}/{len(announcements)}] [跳过] {title} ({lang})")
                self.stats["skipped"] += 1
                continue

            self._emit(
                f"  [{i}/{len(announcements)}] 下载({lang}): {title}",
                progress=i, total=len(announcements),
            )

            if self.download_file(url, save_path):
                self.stats["downloaded"] += 1
            else:
                self._emit(f"    [失败] {title}")
                self.stats["failed"] += 1

            self._delay()

    def print_summary(self):
        """打印下载统计"""
        self._emit(f"\n{'='*60}")
        self._emit("港股下载完成! 统计信息:")
        self._emit(f"  总公告数: {self.stats['total']}")
        self._emit(f"  已下载:   {self.stats['downloaded']}")
        self._emit(f"  已跳过:   {self.stats['skipped']} (文件已存在)")
        self._emit(f"  失败:     {self.stats['failed']}")
        self._emit(f"  保存目录: {self.output_dir}")
        self._emit(f"{'='*60}", done=True, stats=self.stats)
