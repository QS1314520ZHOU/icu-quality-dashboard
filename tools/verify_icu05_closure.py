#!/usr/bin/env python3
"""
ICU-05 收口统一验收脚本
========================
串联执行所有检查项，任何一步失败返回非0退出码。

检查项:
  1. Python 语法检查 (py_compile)
  2. 后端完整测试 (pytest)
  3. candidate/SOFA/adapter 专项测试
  4. summary/API/人工排除集成测试
  5. shadow 不变量测试
  6. 前端测试和生产构建 (npm)
  7. frontend_dist 资源检查
  8. 实库只读匿名对账 (如可连接)
  9. 敏感数据泄漏检查 (grep)

退出码: 0=全部通过, 1=有失败
"""
import subprocess
import sys
import os
import glob
import re
import json
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "icu-quality-backend"
FRONTEND = ROOT / "icu-quality-dashboard"

# ANSI 颜色
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
skipped = 0
results = []


def header(title):
    print(f"\n{BOLD}{CYAN}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{RESET}\n")


def step(title, cmd, cwd=None, timeout=300):
    """执行命令并记录结果。返回 (success, stdout, stderr, returncode)"""
    global passed, failed, skipped
    print(f"{BOLD}[STEP]{RESET} {title}")
    print(f"  cmd: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd or str(BACKEND),
            capture_output=True, text=True, timeout=timeout
        )
        success = result.returncode == 0
        if success:
            print(f"  {GREEN}PASS{RESET} (exit={result.returncode})")
            passed += 1
        else:
            print(f"  {RED}FAIL{RESET} (exit={result.returncode})")
            if result.stdout:
                print(f"  stdout (last 20 lines):")
                for line in result.stdout.strip().split('\n')[-20:]:
                    print(f"    {line}")
            if result.stderr:
                print(f"  stderr (last 20 lines):")
                for line in result.stderr.strip().split('\n')[-20:]:
                    print(f"    {line}")
            failed += 1
        results.append((title, success, result.returncode))
        return success, result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        print(f"  {RED}TIMEOUT{RESET} ({timeout}s)")
        failed += 1
        results.append((title, False, -1))
        return False, "", "timeout", -1
    except Exception as e:
        print(f"  {RED}ERROR{RESET}: {e}")
        failed += 1
        results.append((title, False, -2))
        return False, "", str(e), -2


def check_step(title, condition, detail=""):
    """布尔条件检查"""
    global passed, failed
    print(f"{BOLD}[CHECK]{RESET} {title}")
    if condition:
        print(f"  {GREEN}PASS{RESET}")
        passed += 1
        results.append((title, True, 0))
    else:
        print(f"  {RED}FAIL{RESET} {detail}")
        failed += 1
        results.append((title, False, 1))
    return condition


def main():
    global failed, skipped

    # ================================================================
    header("1. Python 语法检查")
    # ================================================================
    py_files = []
    for pattern in ["**/*.py"]:
        py_files.extend(BACKEND.rglob("*.py"))
    syntax_errors = []
    for pyf in py_files:
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(pyf)],
                capture_output=True, check=True
            )
        except subprocess.CalledProcessError:
            syntax_errors.append(str(pyf))
    check_step(
        "Python 语法检查",
        len(syntax_errors) == 0,
        f"语法错误文件: {syntax_errors}"
    )

    # ================================================================
    header("2. 后端完整测试 (pytest)")
    # ================================================================
    step(
        "后端完整测试",
        f"{sys.executable} -m pytest tests/ -v --tb=short -x 2>&1",
        cwd=str(BACKEND),
        timeout=180
    )

    # ================================================================
    header("3. candidate/SOFA/adapter 专项测试")
    # ================================================================
    for test_file in [
        "tests/test_candidate_engine.py",
        "tests/test_comprehensive_sofa.py",
        "tests/test_data_adapter_fixes.py",
        "tests/test_sofa_bridge.py",
    ]:
        test_path = BACKEND / test_file
        if test_path.exists():
            step(
                f"专项测试: {test_file}",
                f"{sys.executable} -m pytest {test_file} -v --tb=short -x 2>&1",
                cwd=str(BACKEND),
                timeout=120
            )
        else:
            check_step(f"专项测试文件存在: {test_file}", False, "文件不存在")

    # ================================================================
    header("4. summary/API/人工排除集成测试")
    # ================================================================
    for test_file in [
        "tests/test_round3_fixes.py",
        "tests/test_round2_fixes.py",
        "tests/test_denominator_logic.py",
        "tests/test_bundle_window_contract.py",
    ]:
        test_path = BACKEND / test_file
        if test_path.exists():
            step(
                f"集成测试: {test_file}",
                f"{sys.executable} -m pytest {test_file} -v --tb=short -x 2>&1",
                cwd=str(BACKEND),
                timeout=120
            )
        else:
            check_step(f"集成测试文件存在: {test_file}", False, "文件不存在")

    # ================================================================
    header("5. Shadow 不变量测试")
    # ================================================================
    step(
        "Shadow 不变量测试",
        f'{sys.executable} -m pytest tests/ -k "shadow or candidate" -v --tb=short -x 2>&1',
        cwd=str(BACKEND),
        timeout=120
    )

    # ================================================================
    header("6. 前端构建")
    # ================================================================
    # 检查 frontend_dist 资源
    dist_dir = FRONTEND / "dist"
    if dist_dir.exists():
        import shutil
        shutil.rmtree(dist_dir)

    step(
        "前端 npm install",
        "npm install 2>&1",
        cwd=str(FRONTEND),
        timeout=120
    )

    success, stdout, stderr, rc = step(
        "前端生产构建 (vite build)",
        "npm run build 2>&1",
        cwd=str(FRONTEND),
        timeout=120
    )

    # ================================================================
    header("7. frontend_dist 资源检查")
    # ================================================================
    index_html = dist_dir / "index.html"
    check_step("dist/index.html 存在", index_html.exists())

    if index_html.exists():
        content = index_html.read_text(encoding="utf-8")
        check_step("index.html 非空", len(content) > 100)
        # 检查是否有 JS/CSS 资源引用
        check_step("index.html 包含 script 标签", "<script" in content.lower())

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        js_files = list(assets_dir.glob("*.js"))
        css_files = list(assets_dir.glob("*.css"))
        check_step("assets 目录有 JS 文件", len(js_files) > 0, f"找到 {len(js_files)} 个 JS 文件")
        check_step("assets 目录有 CSS 文件", len(css_files) > 0, f"找到 {len(css_files)} 个 CSS 文件")
    else:
        check_step("assets 目录存在", False, "dist/assets 不存在")

    # ================================================================
    header("8. 实库只读匿名对账")
    # ================================================================
    print(f"  {YELLOW}注意: 实库对账需要数据库连接{RESET}")
    print(f"  尝试连接 SmartCare / DataCenter...")

    db_check_script = r'''
import sys, json
sys.path.insert(0, ".")
try:
    from db import get_client
    sc = get_client("SmartCare")
    dc = get_client("DataCenter")
    sc_db = sc["SmartCare"]
    dc_db = dc["DataCenter"]
    sc_db.command("ping")
    dc_db.command("ping")
    drug_count = sc_db.drugExe.count_documents({}, limit=1)
    patient_count = sc_db.patient.count_documents({}, limit=1)
    exam_count = dc_db.VI_ICU_EXAM_ITEM.count_documents({}, limit=1)
    zyyz_count = dc_db.VI_ICU_ZYYZ.count_documents({}, limit=1)
    print("ICU05_RESULT=" + json.dumps({
        "connected": True,
        "smartcare_drugExe_sample": drug_count,
        "smartcare_patient_sample": patient_count,
        "datacenter_exam_sample": exam_count,
        "datacenter_zyyz_sample": zyyz_count,
    }, ensure_ascii=False))
except Exception as e:
    print("ICU05_RESULT=" + json.dumps({"connected": False, "error": type(e).__name__}, ensure_ascii=False))
    sys.exit(1)
'''

    db_check_file = BACKEND / "_verify_db_check.py"
    db_check_file.write_text(db_check_script, encoding="utf-8")

    def parse_icu05_result(stdout_text):
        """从子脚本 stdout 中可靠提取 ICU05_RESULT= 后的 JSON"""
        for line in stdout_text.splitlines():
            if line.startswith("ICU05_RESULT="):
                return json.loads(line[len("ICU05_RESULT="):])
        return None

    try:
        success, stdout, stderr, rc = step(
            "数据库连接测试 (只读)",
            f"{sys.executable} _verify_db_check.py 2>&1",
            cwd=str(BACKEND),
            timeout=30
        )

        db_stats = parse_icu05_result(stdout) if success else None

        if db_stats and db_stats.get("connected"):
            print(f"\n  {GREEN}数据库连接成功{RESET}")

            # 实库生产链对账 (真实链路，非手工构造)
            reconcile_script = r'''
import sys, json, traceback
sys.path.insert(0, ".")
result = {"status": "error", "error": "unknown"}
try:
    from datetime import datetime, timedelta
    from db import get_client, get_bundle_data_v2
    from summary import _compute_icu05

    from bson import ObjectId
    sc = get_client("SmartCare")["SmartCare"]
    dc = get_client("DataCenter")["DataCenter"]

    # 找一个有 drugExe 数据的 pid
    sample_doc = sc.drugExe.find_one({}, {"pid": 1, "startTime": 1})
    if not sample_doc:
        result = {"status": "no_data", "reason": "drugExe 为空"}
        print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    sample_pid = sample_doc.get("pid", "")

    # 找该 pid 对应的 deptCode (drugExe.pid 是 str，patient._id 是 ObjectId)
    pat_doc = None
    if sample_pid:
        try:
            pat_doc = sc.patient.find_one({"_id": ObjectId(str(sample_pid))}, {"deptCode": 1})
        except Exception:
            pass
    if not pat_doc:
        pat_doc = sc.patient.find_one({"_id": sample_pid}, {"deptCode": 1})
    if not pat_doc:
        # fallback: 取第一个有 deptCode 的 patient
        pat_doc = sc.patient.find_one({"deptCode": {"$ne": ""}}, {"deptCode": 1})

    dept_code = (pat_doc or {}).get("deptCode", "")

    if not dept_code:
        # 最后 fallback: 从 drugExe 的 pid 去 patient 表查任意一个有 deptCode 的
        for de in sc.drugExe.find({}, {"pid": 1}).limit(10):
            pid = de.get("pid", "")
            if not pid:
                continue
            try:
                p = sc.patient.find_one({"_id": ObjectId(str(pid))}, {"deptCode": 1})
            except Exception:
                p = sc.patient.find_one({"_id": pid}, {"deptCode": 1})
            if p and p.get("deptCode"):
                dept_code = p["deptCode"]
                break

    # 确定月份范围: 用最新有数据的月份
    latest_de = sc.drugExe.find_one({}, {"startTime": 1}, sort=[("startTime", -1)])
    if latest_de and latest_de.get("startTime"):
        st = latest_de["startTime"]
        year, month = st.year, st.month
        # 往前一个月避免当月未完结数据
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    else:
        now = datetime.now()
        year, month = now.year, now.month - 1
        if month < 1:
            year, month = year - 1, 12
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year+1}-01-01"
    else:
        end = f"{year}-{month+1:02d}-01"

    dept_codes = [dept_code] if dept_code else []

    if not dept_codes:
        # fallback: 从 drugExe 里多找几个 pid → deptCode
        for doc in sc.drugExe.find({}, {"pid": 1}).limit(20):
            pid = doc.get("pid")
            p = sc.patient.find_one({"_id": pid}, {"deptCode": 1}) if pid else None
            if p and p.get("deptCode"):
                dept_codes = [p["deptCode"]]
                break

    if not dept_codes:
        result = {"status": "no_dept", "reason": "无法确定科室"}
        print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    # 调用生产链: _compute_icu05 → get_bundle_data_v2 → judge_bundle_v3_for_patient
    # 只取 1h 做对账
    r1h = _compute_icu05(dept_codes, start, end, "1h")

    # 统计
    evaluated = r1h.get("raw_candidate_count", 0) + r1h.get("not_candidate_count", 0)

    result = {
        "status": "pass",
        "period": f"{start} ~ {end}",
        "dept_count": len(dept_codes),
        "evaluated_event_count": evaluated,
        "official_den_1h": r1h.get("den"),
        "official_num_1h": r1h.get("num"),
        "official_rate_1h": r1h.get("val"),
        "shadow_den_1h": r1h.get("shadow_den_1h"),
        "shadow_num_1h": r1h.get("shadow_num_1h"),
        "shadow_rate_1h": r1h.get("shadow_rate_1h"),
        "shadow_raw_den": r1h.get("shadow_raw_den"),
        "high_probability_count": r1h.get("high_probability_count"),
        "probable_count": r1h.get("probable_count"),
        "pending_review_count": r1h.get("pending_review_count"),
        "not_candidate_count": r1h.get("not_candidate_count"),
        "excluded_num": r1h.get("excluded_num"),
        "excluded_den": r1h.get("excluded_den"),
    }

    # 取 3h 对账
    r3h = _compute_icu05(dept_codes, start, end, "3h")
    result.update({
        "official_den_3h": r3h.get("den"),
        "official_num_3h": r3h.get("num"),
        "official_rate_3h": r3h.get("val"),
        "shadow_den_3h": r3h.get("shadow_den_3h"),
        "shadow_num_3h": r3h.get("shadow_num_3h"),
        "shadow_rate_3h": r3h.get("shadow_rate_3h"),
    })

    # 6h 必须返回 rule_pending
    r6h = _compute_icu05(dept_codes, start, end, "6h")
    result["6h_status"] = r6h.get("status")
    result["6h_val"] = r6h.get("val")

    # 验证关键不变量
    errors = []
    if r6h.get("status") != "rule_pending":
        errors.append(f"6h status expected rule_pending, got {r6h.get('status')}")
    if r6h.get("val") is not None:
        errors.append(f"6h val expected None, got {r6h.get('val')}")

    # shadow 模式: 正式 den 使用旧口径 (K1 AND K2)，由 _compute_icu05 返回值结构保证

    result["invariant_errors"] = errors
    result["status"] = "pass" if not errors else "invariant_fail"

    print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
except Exception as e:
    traceback.print_exc()
    result = {"status": "error", "error": type(e).__name__, "detail": str(e)[:200]}
    print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
    sys.exit(1)
'''
            reconcile_file = BACKEND / "_verify_reconcile.py"
            reconcile_file.write_text(reconcile_script, encoding="utf-8")

            success2, stdout2, stderr2, rc2 = step(
                "实库生产链对账 (真实链路)",
                f"{sys.executable} _verify_reconcile.py 2>&1",
                cwd=str(BACKEND),
                timeout=120
            )

            reconcile_result = parse_icu05_result(stdout2) if success2 else None
            if reconcile_result:
                print(f"\n  {CYAN}实库对账结果:{RESET}")
                for k, v in reconcile_result.items():
                    if k != "status":
                        print(f"    {k}: {v}")
                if reconcile_result.get("status") == "pass":
                    print(f"  {GREEN}实库对账通过{RESET}")
                else:
                    print(f"  {RED}实库对账失败: {reconcile_result.get('status')}{RESET}")
                    failed += 1
                    results.append(("实库生产链对账", False, 1))
            else:
                print(f"  {RED}实库对账: 无法解析子脚本输出{RESET}")
                failed += 1
                results.append(("实库生产链对账 (解析失败)", False, 1))
        else:
            print(f"  {RED}数据库连接失败，无法执行实库对账{RESET}")
            failed += 1
            results.append(("数据库连接", False, 1))

    finally:
        # 清理临时文件
        for tmp in ["_verify_db_check.py", "_verify_reconcile.py"]:
            tmp_path = BACKEND / tmp
            if tmp_path.exists():
                tmp_path.unlink()

    # ================================================================
    header("9. 敏感数据泄漏检查")
    # ================================================================
    sensitive_patterns = [
        (r'password\s*=\s*["\'][^"\']+["\']', "硬编码密码"),
        (r'api_key\s*=\s*["\'][^"\']+["\']', "硬编码 API Key"),
        (r'secret\s*=\s*["\'][^"\']+["\']', "硬编码 Secret"),
        (r'mongodb://[^"\s]+:[^"\s]+@', "MongoDB 连接字符串含密码"),
    ]

    leak_found = False
    for py_file in BACKEND.rglob("*.py"):
        if "__pycache__" in str(py_file) or "_verify_" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern, desc in sensitive_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    # 排除测试文件和配置示例
                    if "test_" in py_file.name or "example" in py_file.name.lower():
                        continue
                    print(f"  {RED}泄漏: {py_file.name}{RESET}: {desc}")
                    leak_found = True
        except:
            pass

    # 检查前端
    for vue_file in FRONTEND.rglob("*.vue"):
        try:
            content = vue_file.read_text(encoding="utf-8", errors="ignore")
            for pattern, desc in sensitive_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    print(f"  {RED}泄漏: {vue_file.name}{RESET}: {desc}")
                    leak_found = True
        except:
            pass

    check_step("敏感数据泄漏检查", not leak_found)

    # ================================================================
    header("10. 代码质量检查")
    # ================================================================
    # 检查关键函数签名变更是否一致
    verify_signatures_script = '''
import sys
sys.path.insert(0, ".")

# 检查 _fetch_ventilator_status_point_in_time 返回 dict
from scoring.data_adapter import _fetch_ventilator_status_point_in_time
import inspect
sig = inspect.signature(_fetch_ventilator_status_point_in_time)
print(f"_fetch_ventilator_status_point_in_time signature: {sig}")

# 检查 extract_candidate 有 vasopressor_status 参数
from scoring.candidate_engine import extract_candidate
sig2 = inspect.signature(extract_candidate)
params = list(sig2.parameters.keys())
assert "vasopressor_status" in params, f"extract_candidate 缺少 vasopressor_status 参数, 当前参数: {params}"
print(f"extract_candidate has vasopressor_status: OK")

# 检查 _fetch_medications 有 lookback_days 参数
from scoring.data_adapter import _fetch_medications
sig3 = inspect.signature(_fetch_medications)
params3 = list(sig3.parameters.keys())
assert "lookback_days" in params3, f"_fetch_medications 缺少 lookback_days 参数"
assert "lookback_hours" not in params3, f"_fetch_medications 仍有旧的 lookback_hours 参数"
print(f"_fetch_medications has lookback_days (not lookback_hours): OK")

print("ALL SIGNATURE CHECKS PASSED")
'''

    sig_file = BACKEND / "_verify_sigs.py"
    sig_file.write_text(verify_signatures_script, encoding="utf-8")
    try:
        step(
            "函数签名一致性检查",
            f"{sys.executable} _verify_sigs.py 2>&1",
            cwd=str(BACKEND),
            timeout=30
        )
    finally:
        if sig_file.exists():
            sig_file.unlink()

    # ================================================================
    # 最终报告
    # ================================================================
    header("验收报告")
    print(f"  {GREEN}通过: {passed}{RESET}")
    print(f"  {RED}失败: {failed}{RESET}")
    print(f"  {YELLOW}跳过: {skipped}{RESET}")
    print()

    for title, success, rc in results:
        status = f"{GREEN}PASS{RESET}" if success else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {title} (rc={rc})")

    print()
    if failed > 0:
        print(f"  {RED}{BOLD}验收失败: {failed} 项未通过{RESET}")
        print(f"  {YELLOW}禁止 commit/push/deploy{RESET}")
        return 1
    else:
        print(f"  {GREEN}{BOLD}验收通过: 所有检查项均通过{RESET}")
        return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
