# -*- coding: utf-8 -*-
"""打包验收：走 FastAPI 真实接口验证 ICU-07 的比率与明细。

用法: python scripts/icu07_verify_api.py [科室] [年月]
"""
import sys, io, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import main as app_main

DEPT = sys.argv[1] if len(sys.argv) > 1 else "3439"
PERIOD = sys.argv[2] if len(sys.argv) > 2 else "2026-09"

client = TestClient(app_main.app)

ok = True


def check(cond, msg):
    global ok
    print(("   ✔ " if cond else "   ✘ ") + msg)
    if not cond:
        ok = False


print("=" * 70)
print("① /api/summary/list  (指标卡片上显示的比率)")
r = client.get("/api/summary/list",
               params={"dept": DEPT, "start_period": PERIOD, "end_period": PERIOD})
r.raise_for_status()
rows = [x for x in r.json() if x.get("indicator") == "ICU-07"]
for row in rows:
    n, d, v = row.get("numerator"), row.get("denominator"), row.get("value")
    print(f"   {DEPT} {PERIOD}  {n}/{d} = {v}%   (API 返回值)")
    live = round(n / d * 100, 1) if d else None
    check(live == v, f"存储值与 n/d 重算一致 ({v} vs {live})")
    print(f"   updated_at: {row.get('updated_at')}")
    print(f"   num_stay: {row.get('num_stay', row.get('raw_num', '-'))}  "
          f"den_stay: {row.get('den_stay', row.get('raw_den', '-'))}")
if not rows:
    check(False, "未返回 ICU-07 行")
    print(json.dumps(r.json()[:3], ensure_ascii=False, default=str, indent=2))

print("=" * 70)
print(f"② /api/indicators/ICU-07/detail  icu_unit={DEPT} period={PERIOD}")
got = {}
for part in ("numerator", "denominator"):
    r2 = client.get("/api/indicators/ICU-07/detail",
                    params={"period": PERIOD, "part": part,
                            "icu_unit": DEPT, "nocache": "true"})
    print(f"   [{part}] HTTP {r2.status_code}")
    if r2.status_code != 200:
        check(False, f"{part} 明细接口失败")
        print(r2.text[:400])
        continue
    data = r2.json()
    items = data.get("patients") or []
    got[part] = items
    print(f"   count={data.get('count')} 返回={len(items)}")
    if items:
        print(f"     列: {list(items[0].keys())}")
        for it in items[:3]:
            print(f"     {it}")
    # Vue 列表 key 必须唯一（detail_id 优先，其次 patient_id）
    keys = [i.get("detail_id") or i.get("patient_id") for i in items]
    check(len(keys) == len(set(keys)), f"{part} 明细 key 唯一 ({len(set(keys))}/{len(keys)})")

    if part == "denominator":
        check(len(items) == (rows[0]["denominator"] if rows else -1),
              f"分母明细行数 {len(items)} == 汇总分母 {rows[0]['denominator'] if rows else '?'}")
        depts = {str(i.get("dept")) for i in items}
        check(depts == {DEPT}, f"分母明细科室集合 = {depts} (应为 {{{DEPT}}})")
        check(all(i.get("patient_id") == i.get("mrn") for i in items),
              "分母明细 住院号列 == mrn")
    else:
        check(len(items) == (rows[0]["numerator"] if rows else -1),
              f"分子明细行数 {len(items)} == 汇总分子 {rows[0]['numerator'] if rows else '?'}")
        nm = {i.get("mrn") for i in items if i.get("mrn")}
        print(f"     分子明细 mrn 去重 = {len(nm)}")
        check(all(i.get("patient_id") == i.get("mrn") for i in items),
              "分子明细 住院号列 == mrn")

if len(got) == 2:
    n_ids = {i.get("detail_id") for i in got["numerator"]}
    d_ids = {i.get("detail_id") for i in got["denominator"]}
    check(n_ids <= d_ids, f"分子明细 detail_id ⊆ 分母明细 detail_id "
                          f"(分子独有 {len(n_ids - d_ids)})")
    n_mrn = {i.get("mrn") for i in got["numerator"]}
    d_mrn = {i.get("mrn") for i in got["denominator"]}
    check(n_mrn <= d_mrn, f"分子明细 mrn ⊆ 分母明细 mrn "
                          f"(分子 {len(n_mrn)} 人 / 分母 {len(d_mrn)} 人)")

print("=" * 70)
print("③ 明细缓存（Mongo icu_indicator_detail_cache）")
_cache_coll = app_main._get_detail_cache_collection()
print(f"   当前 CACHE_VERSION = {app_main.CACHE_VERSION}")
if _cache_coll is None:
    print("   (无明细缓存集合)")
else:
    docs = list(_cache_coll.find({"code": "ICU-07", "dept_code": DEPT,
                                  "period": PERIOD},
                                 {"part": 1, "cache_version": 1, "count": 1,
                                  "updated_at": 1, "_id": 0}))
    for d in docs:
        print("   ", d)
    check(len(docs) == 2, f"ICU-07/{DEPT}/{PERIOD} 有 2 个 part 的缓存 (实际 {len(docs)})")
    check(all(d.get("cache_version") == app_main.CACHE_VERSION for d in docs),
          "缓存条目均为当前版本")
    stale = _cache_coll.count_documents({"code": "ICU-07",
                                         "cache_version": {"$ne": app_main.CACHE_VERSION}})
    print(f"   旧版本残留条目 = {stale} (写入时会被清理)")

    # 走一遍「历史期读 Mongo 缓存」的完整路径，确认与直算结果一致
    app_main._cache_clear()
    cached_hits = 0
    for part in ("numerator", "denominator"):
        r3 = client.get("/api/indicators/ICU-07/detail",
                        params={"period": PERIOD, "part": part, "icu_unit": DEPT})
        if r3.status_code == 200 and r3.json().get("patients") is not None:
            cached_hits += 1
    check(cached_hits == 2, "走缓存路径能取到 2 个 part 的明细")

print("=" * 70)
print(("验收通过 ✔" if ok else "验收失败 ✘") +
      f"   ICU-07 / {DEPT} / {PERIOD}")
sys.exit(0 if ok else 1)
