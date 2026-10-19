#!/usr/bin/env python3
# -*- keep-utf8 -*-
"""一键自检 EvoFlow 日志链路：环境变量 → 日志目录 → 文件在写 → LangGraph 开关 → gateway 存活 → 实测写入。

用法（仓库根目录）:
    backend\\.venv\\Scripts\\python.exe scripts\\check_logging.py
    backend\\.venv\\Scripts\\python.exe scripts\\check_logging.py --port 8070

每一步输出 PASS / WARN / FAIL 与下一步建议；最后写一条 [check_logging] probe 标记行到
真实日志文件——在文件里 grep 到它即证明日志管线通路正常。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
for p in (_BACKEND, _BACKEND / "packages" / "harness"):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

_RESULTS: list[tuple[str, str, str]] = []


def step(name: str, ok: bool, detail: str, hint: str = "", *, warn_only: bool = False) -> None:
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    _RESULTS.append((status, name, hint if not ok else ""))
    mark = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
    print(f"{mark} {name}: {detail}")
    if not ok and hint:
        print(f"       -> {hint}")


def main() -> int:
    parser = argparse.ArgumentParser(description="EvoFlow logging health check")
    parser.add_argument("--port", type=int, default=int(os.getenv("EVOFLOW_GATEWAY_PORT") or 8012))
    args = parser.parse_args()

    print("=" * 72)
    print("EvoFlow 日志链路自检", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 72)

    print("\n[1/6] 相关环境变量")
    keys = [
        "EVOFLOW_HOME",
        "EVOFLOW_LOGS_DIR",
        "EVOFLOW_SHOW_LANGGRAPH_LOGS",
        "EVOFLOW_SHOW_LANGGRAPH_POLL_LOGS",
        "EVOFLOW_ENABLE_CONSOLE_LOG",
        "EVOFLOW_DISABLE_CONSOLE_LOG",
        "EVOFLOW_GATEWAY_LOG_LEVEL",
        "LOG_LEVEL",
    ]
    env_vals = {k: os.getenv(k, "") for k in keys}
    for k, v in env_vals.items():
        print(f"       {k} = {v or '(未设置)'}")
    step(
        "环境变量可读",
        True,
        "见上表",
    )
    if not env_vals["EVOFLOW_SHOW_LANGGRAPH_LOGS"]:
        print("       -> 提示: 要看完整 LangGraph 运行日志, 设 EVOFLOW_SHOW_LANGGRAPH_LOGS=1 后重启 gateway")

    print("\n[2/6] 日志目录解析（走真实代码路径）")
    log_dir: Path | None = None
    try:
        from app.gateway.logging_setup import resolve_gateway_logs_dir

        log_dir = resolve_gateway_logs_dir()
        step("resolve_gateway_logs_dir", True, str(log_dir))
        if not log_dir.is_dir():
            step("日志目录存在", False, f"{log_dir} 不存在", "gateway 启动时会自动 mkdir；若刚清空属正常，先启动 gateway")
    except Exception as exc:
        step("resolve_gateway_logs_dir", False, f"导入/解析失败: {exc}", "检查 backend/ 代码是否完整、venv 是否正确")

    print("\n[3/6] 日志文件状态（是否在写）")
    latest_path: Path | None = None
    if log_dir is not None and log_dir.is_dir():
        candidates = sorted(log_dir.glob("gateway-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            step("gateway-*.log 存在", False, f"{log_dir} 下没有 gateway-*.log", "gateway 未启动或日志写到了别处 — 对照 [2/6] 解析结果")
        else:
            latest_path = candidates[0]
            age_s = time.time() - latest_path.stat().st_mtime
            size_kb = latest_path.stat().st_size / 1024
            step("最新日志文件", True, f"{latest_path.name} ({size_kb:.0f} KB, {age_s:.0f} 秒前更新)")
            if age_s > 600:
                step("文件在更新", False, f"最后写入是 {age_s / 60:.0f} 分钟前", "gateway 可能没在跑或已卡死 — 看 [5/6] 存活检查；确认你看的目录和 [2/6] 一致")
            else:
                step("文件在更新", True, f"{age_s:.0f} 秒内有写入")
            today = datetime.now().strftime("%Y-%m-%d")
            if not any(p.name.endswith(f"{today}.log") for p in candidates):
                step("今日日志文件", False, f"没有 {today} 的文件", "gateway 今天没启动成功, 或当前日期与日志文件日期不一致")

    print("\n[4/6] LangGraph 日志开关与压制状态")
    try:
        from app.gateway.logging_setup import _QUIET_LOGGER_LEVELS, _show_langgraph_logs

        show_lg = _show_langgraph_logs()
        lg_quiet = {n: lvl for n, lvl in _QUIET_LOGGER_LEVELS.items() if n.startswith("langgraph")}
        import logging

        if show_lg:
            step(
                "EVOFLOW_SHOW_LANGGRAPH_LOGS",
                True,
                "已开启 — langgraph 压制被跳过, 运行日志按正常级别输出",
            )
        else:
            worst = min(lg_quiet.values()) if lg_quiet else logging.CRITICAL
            silenced = [n for n, l in lg_quiet.items() if l >= logging.WARNING]
            step(
                "EVOFLOW_SHOW_LANGGRAPH_LOGS",
                False,
                f"未开启 — {len(silenced)} 个 langgraph logger 被压到 WARNING/CRITICAL (最低 {logging.getLevelName(worst)})",
                "设 EVOFLOW_SHOW_LANGGRAPH_LOGS=1 后重启 gateway; 这就是『日志里看不到 langgraph_runtime_inmem』的原因",
                warn_only=True,
            )
    except Exception as exc:
        step("logging_setup 状态", False, f"读取失败: {exc}")

    print("\n[5/6] Gateway 进程存活")
    url = f"http://127.0.0.1:{args.port}/health/liveness"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        step("health/liveness", True, f"{url} -> {body}")
    except Exception as exc:
        step("health/liveness", False, f"{url} 不可达: {exc}", f"gateway 没在跑: 跑 dev-stack-isolated.bat 或 --port 指定正确端口(当前 {args.port})")

    print("\n[6/6] 实测写入（日志管线端到端验证）")
    if latest_path is not None:
        probe = f"[check_logging] probe write at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — grep 这行即管线正常"
        try:
            from app.gateway.logging_setup import configure_gateway_file_logging

            configure_gateway_file_logging(log_dir=latest_path.parent, log_name="gateway.log", force=True)
            logging.getLogger("app.gateway.check_logging").warning(probe)
            written = probe in latest_path.read_text(encoding="utf-8", errors="replace")
            step("probe 写入", written, f"标记行{'已' if written else '未'}写入 {latest_path.name}", "未写入说明 handler/format 环节异常, 把此输出发给开发排查")
        except Exception as exc:
            step("probe 写入", False, f"写入失败: {exc}", "目录只读/权限/磁盘满 均会导致日志静默丢失")
    else:
        step("probe 写入", False, "没有最新日志文件可写", "先启动 gateway 再跑本脚本")

    print("\n" + "=" * 72)
    fails = [r for r in _RESULTS if r[0] == "FAIL"]
    warns = [r for r in _RESULTS if r[0] == "WARN"]
    print(f"结果: {len(_RESULTS) - len(fails) - len(warns)} PASS / {len(warns)} WARN / {len(fails)} FAIL")
    for status, name, hint in fails + warns:
        if hint:
            print(f"  [{status}] {name}: {hint}")
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())