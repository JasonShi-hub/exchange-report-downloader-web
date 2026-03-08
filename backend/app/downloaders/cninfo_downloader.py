#!/usr/bin/env python3
"""
巨潮资讯网(cninfo.com.cn)上市公司公告自动下载脚本

用法:
    python cninfo_downloader.py 000001 600036 --start 2023-01-01 --end 2024-12-31
    python cninfo_downloader.py 000001 --start 2023-01-01 --end 2024-12-31 --category 年报 半年报
    python cninfo_downloader.py 000001 --start 2023-01-01 --end 2024-12-31 --output ~/my_reports/
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import random
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    print("请运行: pip install requests")
    sys.exit(1)

# ============================================================
# 常量与配置
# ============================================================

API_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
DOWNLOAD_BASE_URL = "http://static.cninfo.com.cn/"
DEFAULT_OUTPUT = os.path.expanduser("~/Downloads/cninfo")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "http://www.cninfo.com.cn",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/search",
}

# 报告类别映射: 中文名 -> API category code
CATEGORY_MAP = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
    "业绩预告": "category_yjygjxz_szsh",
    "权益分派": "category_qyfpxzcs_szsh",
    "董事会": "category_dshgg_szsh",
    "监事会": "category_jshgg_szsh",
    "股东大会": "category_gddh_szsh",
    "日常经营": "category_rcjy_szsh",
    "公司治理": "category_gszl_szsh",
    "中介报告": "category_zjbg_szsh",
    "调研报告": "category_mdcf_szdy;category_lyhd_szdy;category_dyhd_szdy;category_glzd_szdy",
    "首发": "category_sf_szsh",
    "增发": "category_zf_szsh",
    "股权激励": "category_gqjl_szsh",
    "配股": "category_pg_szsh",
    "解禁": "category_jj_szsh",
    "公司债": "category_gsz_szsh",
    "可转债": "category_kzz_szsh",
    "其他融资": "category_qtrz_szsh",
    "股权变动": "category_gqbd_szsh",
    "补充更正": "category_bcgz_szsh",
    "澄清致歉": "category_cqdq_szsh",
    "风险提示": "category_fxts_szsh",
    "特别处理和退市": "category_tbclts_szsh",
}

# 根据公告标题关键词判断报告所属类别（用于目录分类）
TITLE_CATEGORY_RULES = [
    ("投资者关系活动记录表", "调研报告"),
    ("投资者关系活动", "调研报告"),
    ("投资者关系管理信息", "调研报告"),
    ("调研活动", "调研报告"),
    ("路演活动", "调研报告"),
    ("媒体采访", "调研报告"),
    ("年度报告", "年报"),
    ("年报", "年报"),
    ("半年度报告", "半年报"),
    ("半年报", "半年报"),
    ("第一季度报告", "一季报"),
    ("一季报", "一季报"),
    ("第三季度报告", "三季报"),
    ("三季报", "三季报"),
    ("第二季度报告", "半年报"),  # 极少见，归入半年报
    ("季度报告", "季报"),
    ("业绩预告", "业绩预告"),
    ("业绩快报", "业绩快报"),
    ("董事会决议", "董事会"),
    ("监事会决议", "监事会"),
    ("股东大会", "股东大会"),
    ("章程", "公司治理"),
    ("审计报告", "中介报告"),
    ("法律意见", "中介报告"),
    ("评估报告", "中介报告"),
    ("招股说明书", "首发"),
    ("配股", "配股"),
    ("增发", "增发"),
    ("可转换", "可转债"),
    ("可转债", "可转债"),
    ("股权激励", "股权激励"),
    ("风险提示", "风险提示"),
    ("更正", "补充更正"),
    ("补充", "补充更正"),
    ("澄清", "澄清致歉"),
    ("致歉", "澄清致歉"),
    ("退市", "特别处理"),
]


# ============================================================
# 工具函数
# ============================================================

def classify_announcement(title: str) -> str:
    """根据公告标题判断报告类别（用于文件夹分类）"""
    for keyword, category in TITLE_CATEGORY_RULES:
        if keyword in title:
            return category
    return "其他公告"


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 200:
        name = name[:200]
    return name


def extract_year_from_date(date_str: str) -> str:
    """从日期字符串中提取年份"""
    match = re.search(r'(\d{4})', date_str)
    return match.group(1) if match else "未知年份"


def expand_category_codes(category_codes: list) -> list[str]:
    """展开类别编码，支持分号分隔、去空、去重、保序。"""
    if not category_codes:
        return []

    flat_codes = []
    seen = set()
    for item in category_codes:
        for code in str(item).split(";"):
            code = code.strip()
            if code and code not in seen:
                seen.add(code)
                flat_codes.append(code)
    return flat_codes


def is_relation_code(code: str) -> bool:
    """判断类别编码是否属于 relation 栏目。"""
    return str(code).endswith("_szdy")


def build_short_doc_key(announcement_id, adjunct_url: str) -> str:
    """生成短且稳定的文档唯一键，避免同名公告误跳过。"""
    aid = re.sub(r'\D', '', str(announcement_id or ""))
    if aid:
        return f"A{aid[-10:]}"
    digest = hashlib.sha1((adjunct_url or "").encode("utf-8")).hexdigest()[:8]
    return f"H{digest}"


def build_output_filename(ann_date: str, title: str, announcement_id, adjunct_url: str) -> str:
    """构建输出文件名：日期_标题_短唯一键.pdf"""
    base = sanitize_filename(f"{ann_date}_{title}")
    doc_key = build_short_doc_key(announcement_id, adjunct_url)

    # 预留 _{key}.pdf，避免标题截断后丢失唯一键
    reserve = len(doc_key) + len("_.pdf")
    max_base_len = max(20, 200 - reserve)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()

    return f"{base}_{doc_key}.pdf"


# ============================================================
# 核心类
# ============================================================

class CninfoDownloader:
    def __init__(self, output_dir: str, delay_range: tuple = (1.0, 3.0), max_retries: int = 3,
                 on_message=None):
        self.output_dir = output_dir
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.on_message = on_message or (lambda msg, **kw: print(msg))
        self.stop_requested = False
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.stats = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        # 初始化session: 访问主页获取cookies
        try:
            self.session.get("http://www.cninfo.com.cn/", timeout=15)
        except requests.RequestException:
            pass

    def _delay(self):
        """请求间随机延时（可被 stop_requested 中断）"""
        remaining = random.uniform(*self.delay_range)
        while remaining > 0 and not self.stop_requested:
            step = min(remaining, 0.3)
            time.sleep(step)
            remaining -= step

    def _emit(self, msg, **kwargs):
        """发送消息（支持回调或print）"""
        self.on_message(msg, **kwargs)

    def lookup_stock_info(self, stock_code: str) -> dict:
        """通过搜索API查询股票的orgId和名称

        Returns: {"code": "000001", "orgId": "gssz0000001", "zwjc": "平安银行"} or None
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.post(SEARCH_URL, data={
                    "keyWord": stock_code,
                    "maxNum": 10,
                }, timeout=15)
                resp.raise_for_status()
                results = resp.json()
                for item in results:
                    if item.get("code") == stock_code and item.get("category") == "A股":
                        return item
                for item in results:
                    if item.get("code") == stock_code:
                        return item
                return None
            except (requests.RequestException, json.JSONDecodeError) as e:
                self._emit(f"  [重试 {attempt}/{self.max_retries}] 查询股票信息失败: {e}")
                if attempt < self.max_retries:
                    self._delay()
        return None

    def query_announcements(self, stock_code: str, org_id: str, start_date: str, end_date: str,
                            category_codes: list = None) -> list:
        """查询指定股票在时间范围内的公告（支持 fulltext/relation 分流合并）"""
        stock_param = f"{stock_code},{org_id}" if org_id else stock_code

        if category_codes is None:
            batches = [self._query_tab(stock_param, start_date, end_date, "fulltext", "")]
        else:
            flat_codes = expand_category_codes(category_codes)
            fulltext_codes = [c for c in flat_codes if not is_relation_code(c)]
            relation_codes = [c for c in flat_codes if is_relation_code(c)]
            batches = []
            if fulltext_codes:
                batches.append(self._query_tab(
                    stock_param, start_date, end_date, "fulltext", ";".join(fulltext_codes)
                ))
            if relation_codes:
                batches.append(self._query_tab(
                    stock_param, start_date, end_date, "relation", ";".join(relation_codes)
                ))
            if not batches:
                return []

        merged_announcements = []
        seen_keys = set()
        for announcements in batches:
            if self.stop_requested:
                break
            for ann in announcements:
                announcement_id = str(ann.get("announcementId") or "").strip()
                if announcement_id:
                    unique_key = f"id:{announcement_id}"
                else:
                    adjunct_url = str(ann.get("adjunctUrl") or "").strip()
                    if adjunct_url:
                        unique_key = f"url:{adjunct_url}"
                    else:
                        title = re.sub(r'</?em>', '', ann.get("announcementTitle", "")).strip()
                        ann_time = str(ann.get("announcementTime") or "").strip()
                        unique_key = f"fallback:{ann_time}:{title}"

                if unique_key in seen_keys:
                    continue
                seen_keys.add(unique_key)
                merged_announcements.append(ann)

        def _announcement_sort_value(ann: dict) -> int:
            value = ann.get("announcementTime", 0)
            if isinstance(value, (int, float)):
                return int(value)
            value_str = str(value).strip()
            if value_str.isdigit():
                return int(value_str)
            try:
                return int(datetime.strptime(value_str[:10], "%Y-%m-%d").timestamp() * 1000)
            except ValueError:
                return 0

        merged_announcements.sort(key=_announcement_sort_value, reverse=True)
        return merged_announcements

    def _query_tab(self, stock_param: str, start_date: str, end_date: str,
                   tab_name: str, category_str: str) -> list:
        """查询指定 tabName 的公告数据（分页+重试）。"""
        all_announcements = []
        se_date = f"{start_date}~{end_date}"
        page = 1
        while True:
            if self.stop_requested:
                self._emit("  [停止] 用户取消操作")
                return all_announcements

            params = {
                "pageNum": page,
                "pageSize": 30,
                "column": "szse",
                "tabName": tab_name,
                "stock": stock_param,
                "searchkey": "",
                "secid": "",
                "plate": "",
                "category": category_str,
                "trade": "",
                "seDate": se_date,
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }

            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = self.session.post(API_URL, data=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except (requests.RequestException, json.JSONDecodeError) as e:
                    self._emit(f"  [重试 {attempt}/{self.max_retries}] 查询第 {page} 页失败: {e}")
                    if attempt == self.max_retries:
                        self._emit(f"  [错误] 第 {page} 页查询失败，跳过后续页面")
                        return all_announcements
                    self._delay()

            announcements = data.get("announcements") or []
            if not announcements:
                break

            all_announcements.extend(announcements)
            total_count = data.get("totalAnnouncement", 0)
            self._emit(
                f"  [{tab_name}] 第 {page} 页: 获取 {len(announcements)} 条 "
                f"(累计 {len(all_announcements)}/{total_count})"
            )

            if len(all_announcements) >= total_count:
                break

            page += 1
            self._delay()

        return all_announcements

    def download_file(self, url: str, save_path: str) -> bool:
        """下载单个文件，支持重试，可被 stop_requested 中断"""
        for attempt in range(1, self.max_retries + 1):
            if self.stop_requested:
                return False
            try:
                resp = self.session.get(url, timeout=60, stream=True)
                resp.raise_for_status()

                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if self.stop_requested:
                            f.close()
                            # 删除未完成的文件
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

    def get_stock_name(self, stock_code: str, announcements: list) -> str:
        """从公告数据中提取股票简称"""
        for ann in announcements:
            name = ann.get("secName", "").strip()
            if name:
                return name
        return stock_code

    def process_stock(self, stock_code: str, start_date: str, end_date: str,
                      category_codes: list = None):
        """处理单只股票的全部下载"""
        if self.stop_requested:
            return

        self._emit(f"\n{'='*60}")
        self._emit(f"正在查询: {stock_code} ({start_date} ~ {end_date})")
        self._emit(f"{'='*60}")

        stock_info = self.lookup_stock_info(stock_code)
        if not stock_info:
            self._emit(f"  [错误] 未找到股票 {stock_code} 的信息，请检查代码是否正确")
            return

        org_id = stock_info.get("orgId", "")
        stock_name = stock_info.get("zwjc", stock_code)
        self._emit(f"  股票: {stock_name} ({stock_code}) orgId={org_id}")

        announcements = self.query_announcements(stock_code, org_id, start_date, end_date, category_codes)

        if not announcements:
            self._emit(f"  未找到 {stock_code} 的公告")
            return

        stock_dir_name = sanitize_filename(f"{stock_code}_{stock_name}")

        self._emit(f"  共找到 {len(announcements)} 条公告")
        self.stats["total"] += len(announcements)

        for i, ann in enumerate(announcements, 1):
            if self.stop_requested:
                self._emit("  [停止] 用户取消操作")
                return

            title = ann.get("announcementTitle", "未知标题")
            title = re.sub(r'</?em>', '', title)
            adjunct_url = ann.get("adjunctUrl", "")
            announcement_id = ann.get("announcementId", "")
            ann_date = ann.get("announcementTime", "")

            if isinstance(ann_date, (int, float)):
                ann_date = datetime.fromtimestamp(ann_date / 1000).strftime("%Y-%m-%d")

            year = extract_year_from_date(ann_date)
            category = classify_announcement(title)

            filename = build_output_filename(ann_date, title, announcement_id, adjunct_url)
            save_dir = os.path.join(self.output_dir, stock_dir_name, category, year)
            save_path = os.path.join(save_dir, filename)

            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                self._emit(f"  [{i}/{len(announcements)}] [跳过] {title}")
                self.stats["skipped"] += 1
                continue

            download_url = DOWNLOAD_BASE_URL + adjunct_url
            self._emit(f"  [{i}/{len(announcements)}] 下载: {title}", progress=i, total=len(announcements))

            if self.download_file(download_url, save_path):
                self.stats["downloaded"] += 1
            else:
                self._emit(f"    [失败] {title}")
                self.stats["failed"] += 1

            self._delay()

    def print_summary(self):
        """打印下载统计"""
        self._emit(f"\n{'='*60}")
        self._emit("下载完成! 统计信息:")
        self._emit(f"  总公告数: {self.stats['total']}")
        self._emit(f"  已下载:   {self.stats['downloaded']}")
        self._emit(f"  已跳过:   {self.stats['skipped']} (文件已存在)")
        self._emit(f"  失败:     {self.stats['failed']}")
        self._emit(f"  保存目录: {self.output_dir}")
        self._emit(f"{'='*60}", done=True, stats=self.stats)


# ============================================================
# 命令行入口
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="巨潮资讯网上市公司公告自动下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s 000001 600036 --start 2023-01-01 --end 2024-12-31
  %(prog)s 000001 --start 2023-01-01 --end 2024-12-31 --category 年报 半年报
  %(prog)s 000001 --start 2024-01-01 --end 2024-12-31 --output ~/my_reports/

可用报告类别:
  年报, 半年报, 一季报, 三季报, 业绩预告, 权益分派,
  董事会, 监事会, 股东大会, 日常经营, 公司治理, 中介报告, 调研报告,
  首发, 增发, 股权激励, 配股, 解禁, 公司债, 可转债,
  其他融资, 股权变动, 补充更正, 澄清致歉, 风险提示, 特别处理和退市
        """,
    )
    parser.add_argument("stocks", nargs="+", help="股票代码，如 000001 600036")
    parser.add_argument("--start", "-s", required=True, help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", "-e", required=True, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--category", "-c", nargs="*", default=None,
                        help="报告类别(可多选)，不指定则下载全部常规公告(不含调研)")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help=f"保存目录 (默认: {DEFAULT_OUTPUT})")
    parser.add_argument("--delay-min", type=float, default=1.0, help="最小请求间隔秒数 (默认: 1.0)")
    parser.add_argument("--delay-max", type=float, default=3.0, help="最大请求间隔秒数 (默认: 3.0)")
    return parser.parse_args()


def main():
    args = parse_args()

    # 验证日期格式
    for date_str, label in [(args.start, "起始日期"), (args.end, "结束日期")]:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"错误: {label} '{date_str}' 格式不正确，请使用 YYYY-MM-DD 格式")
            sys.exit(1)

    # 解析类别
    category_codes = None
    if args.category:
        category_codes = []
        for cat_name in args.category:
            if cat_name in CATEGORY_MAP:
                category_codes.append(CATEGORY_MAP[cat_name])
            else:
                print(f"警告: 未知报告类别 '{cat_name}'，将忽略")
                print(f"  可用类别: {', '.join(CATEGORY_MAP.keys())}")
        if not category_codes:
            print("错误: 没有有效的报告类别")
            sys.exit(1)

    output_dir = os.path.expanduser(args.output)
    os.makedirs(output_dir, exist_ok=True)

    print(f"巨潮资讯网公告下载工具")
    print(f"股票代码: {', '.join(args.stocks)}")
    print(f"时间范围: {args.start} ~ {args.end}")
    print(f"报告类别: {', '.join(args.category) if args.category else '全部常规公告(不含调研)'}")
    print(f"保存目录: {output_dir}")

    downloader = CninfoDownloader(
        output_dir=output_dir,
        delay_range=(args.delay_min, args.delay_max),
    )

    for stock_code in args.stocks:
        downloader.process_stock(stock_code, args.start, args.end, category_codes)

    downloader.print_summary()


if __name__ == "__main__":
    main()
