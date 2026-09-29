#!/usr/bin/env python3
"""侦察: 央行《金融统计数据报告》抓取可行性 + 正文解析
目标: 验证 (1) 官网可达 (2) 报告列表页结构 (3) 正文社融增量累计的正则可提取
"""
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BASE = "https://www.pbc.gov.cn"

def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore"), "utf-8(ignore)"

print("=" * 70)
print("① 栏目列表页可达性")
print("=" * 70)
LIST = f"{BASE}/goutongjiaoliu/113456/113469/index.html"
try:
    html, enc = get(LIST)
    print(f"  OK 编码={enc} 长度={len(html)}")
    links = re.findall(r'href="(/goutongjiaoliu/113456/113469/\d+/index\.html)"[^>]*>([^<]*)<', html)
    print(f"  找到链接 {len(links)} 条, 含'金融统计数据报告'的:")
    n = 0
    for href, text in links:
        if "金融统计数据报告" in text:
            n += 1
            if n <= 6:
                print(f"    {text.strip()[:40]:42s} → {href}")
    print(f"  合计 {n} 条")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")

print()
print("=" * 70)
print("② 单篇报告正文解析(2026年8月)")
print("=" * 70)
ART = f"{BASE}/goutongjiaoliu/113456/113469/2026091414593871200/index.html"
try:
    html, enc = get(ART)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    print(f"  OK 编码={enc} 正文长度={len(text)}")
    # 标题
    m = re.search(r"(20\d{2}年\d{1,2}月金融统计数据报告)", text)
    print(f"  标题: {m.group(1) if m else '未匹配'}")
    # 社融增量累计
    pats = [
        r"社会融资规模增量累计为\s*([\d.]+)\s*万亿元",
        r"社会融资规模增量累计为\s*([\d.]+)\s*亿元",
        r"社会融资规模增量为\s*([\d.]+)\s*万亿元",
        r"社会融资规模增量为\s*([\d.]+)\s*亿元",
    ]
    for p in pats:
        mm = re.findall(p, text)
        print(f"  正则 {p[:36]:38s} → {mm}")
    # 上下文片段
    i = text.find("社会融资规模增量")
    if i >= 0:
        print(f"  上下文: ...{text[max(0,i-60):i+90]}...")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")

print()
print("=" * 70)
print("③ 备用源: 上海金融办/中国财务公司协会(转载, 结构更简单)")
print("=" * 70)
ALT = "https://jrj.sh.gov.cn/SCGK194/20260414/6ddd9e24f07e49438ec397fa2f7fec1c.html"
try:
    html, enc = get(ALT)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    print(f"  OK 编码={enc} 长度={len(text)}")
    for p in [r"社会融资规模增量累计为\s*([\d.]+)\s*万亿元",
              r"社会融资规模增量为\s*([\d.]+)\s*万亿元"]:
        print(f"  {p[:40]:42s} → {re.findall(p, text)}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")
