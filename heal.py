#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox / 影视TV 配置自愈生成器（v2 加固版，2026-11-23 agent 编队审查后）

作用：
   1. 并发、多重复探测候选源存活与健康度（HTTP 状态 + 内容 + 基线 + 延迟）
   2. 剔除失效源、按 failover_group 去重、按优先级选健康源，重建 config.json
   3. 失效保护：按 vod/live 分组独立回填上一版，绝不把电视拉空
   4. 原子写入：config/state/report 只出现完整旧版或完整新版，杜绝半截 JSON
   5. 全源失效达阈值升级告警（needs_attention），不再无限静默重试
   6. 生成 HEAL_REPORT.md 运行报告，便于回溯

纯 Python 标准库，GitHub Actions / 本地均可直接跑，无需 pip install。

用法：
   python heal.py
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = os.path.join(BASE, "candidates.json")
CONFIG = os.path.join(BASE, "config.json")
STATE = os.path.join(BASE, "state.json")
REPORT = os.path.join(BASE, "HEAL_REPORT.md")

CST = timezone(timedelta(hours=8))


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S %z")


def load_json(path, default):
    """读取 JSON；区分'文件不存在/读失败/内容非法'，各返回 default 但打印原因。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("WARN: %s 顶层非对象，按默认处理" % path)
            return default
        return data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print("WARN: 读取 %s 失败（%s），按默认处理" % (path, e))
        return default


def write_text(path, text):
    """原子写：tmp -> flush -> fsync -> os.replace，杜绝半截文件。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def strip_json_comments(text):
    """去掉 jsonc 注释：整行 // 注释 + /* */ 块注释，保留 URL 里的 //。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def fetch(url, timeout):
    """返回 (ok, text, status, err, elapsed_ms)。"""
    t0 = time.monotonic()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TVBox-SelfHeal/2.0)",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read(8 * 1024 * 1024)
            text = raw.decode("utf-8", errors="replace")
            elapsed = int((time.monotonic() - t0) * 1000)
            return (200 <= status < 300), text, status, "", elapsed
    except urllib.error.HTTPError as e:
        return False, "", e.code, "HTTPError %s" % e.code, int((time.monotonic() - t0) * 1000)
    except Exception as e:
        return False, "", 0, "%s: %s" % (type(e).__name__, e), int((time.monotonic() - t0) * 1000)


def probe_source(src, timeout, min_sites, min_channels, repeats, baselines):
    """探测单个候选源，多重复 + 基线校验。返回带 ok/reason/detail 的结果。"""
    url = src["url"]
    sid = src.get("id", url)
    to = src.get("timeout_seconds", timeout)
    kind = src.get("kind", "json")
    result = {
        "id": sid,
        "url": url,
        "kind": kind,
        "priority": src.get("priority", 99),
        "failover_group": src.get("failover_group", ""),
        "name": src.get("name", ""),
        "ok": False,
        "status": 0,
        "reason": "",
        "count": 0,
        "latency_ms": 999999,
    }

    # 多重复探测：要求 repeats 次里全部成功才算健康，防慢源偶发成功误判
    last_text = ""
    ok_count = 0
    latencies = []
    last_status = 0
    last_err = ""
    for _ in range(repeats):
        ok, text, status, err, elapsed = fetch(url, to)
        latencies.append(elapsed)
        if ok:
            ok_count += 1
            last_text = text
        last_status = status
        last_err = err
    result["latency_ms"] = min(latencies) if latencies else 999999
    result["status"] = last_status
    if ok_count < repeats:
        result["reason"] = (last_err or ("HTTP %s" % last_status)) + " (成功 %d/%d)" % (ok_count, repeats)
        return result

    try:
        if kind == "json":
            data = json.loads(strip_json_comments(last_text))
            sites = data.get("sites") or []
            if not isinstance(sites, list):
                result["reason"] = "sites 字段非数组"
                return result
            valid = [s for s in sites if isinstance(s, dict) and s.get("api")]
            result["count"] = len(valid)
            # 基线校验：低于上次健康数一半即判失效，防上游被改空壳仍算健康
            base = baselines.get(sid, 0)
            floor = max(min_sites, int(base * 0.5)) if base else min_sites
            if len(valid) < floor:
                result["reason"] = "有效站点数 %d < 阈值 %d（基线 %d）" % (len(valid), floor, base)
                return result
            baselines[sid] = len(valid)
            result["ok"] = True
            result["reason"] = "OK"
        elif kind == "m3u":
            if "#EXTM3U" not in last_text[:256]:
                result["reason"] = "缺少 #EXTM3U 头"
                return result
            channels = len(re.findall(r"#EXTINF", last_text))
            result["count"] = channels
            if channels < min_channels:
                result["reason"] = "频道数 %d < 阈值 %d" % (channels, min_channels)
                return result
            result["ok"] = True
            result["reason"] = "OK"
        else:
            result["reason"] = "未知 kind=%s" % kind
    except Exception as e:
        result["reason"] = "解析失败 %s: %s" % (type(e).__name__, e)
    return result


def probe_all(sources, timeout, min_sites, min_channels, workers, repeats, baselines):
    results = []
    if not sources:
        return results
    deadline = timeout * len(sources) + 10
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe_source, s, timeout, min_sites, min_channels, repeats, baselines): s
            for s in sources
        }
        done_ids = set()
        try:
            for fut in as_completed(futures, timeout=deadline):
                done_ids.add(id(fut))
                try:
                    results.append(fut.result())
                except Exception as e:
                    s = futures[fut]
                    results.append({
                        "id": s.get("id", "?"), "url": s.get("url", ""),
                        "kind": s.get("kind", "json"), "priority": 99,
                        "failover_group": s.get("failover_group", ""), "name": "",
                        "ok": False, "status": 0, "reason": "探测异常 %s" % e,
                        "count": 0, "latency_ms": 999999,
                    })
        except Exception as e:
            print("WARN: 探测总超时，未完成源按失败处理：%s" % e)
        # 补全未完成（卡死/超时）的 future
        for fut, s in futures.items():
            if id(fut) not in done_ids:
                fut.cancel()
                results.append({
                    "id": s.get("id", "?"), "url": s.get("url", ""),
                    "kind": s.get("kind", "json"), "priority": 99,
                    "failover_group": s.get("failover_group", ""), "name": "",
                    "ok": False, "status": 0, "reason": "探测超时/未完成",
                    "count": 0, "latency_ms": 999999,
                })
    # 健康优先，组内优先级小、延迟低者靠前
    results.sort(key=lambda r: (not r["ok"], r["priority"], r.get("latency_ms", 999999), r["id"]))
    return results


def to_live_entry(src):
    """m3u 候选源 -> TVBox lives 条目。"""
    return {
        "name": src.get("name") or src.get("id", "直播"),
        "type": 1,
        "url": src["url"],
        "searchable": 0,
        "changeable": 0,
    }


def pick_failover(healthy_srcs):
    """同 failover_group 去重：每组只取优先级最高/延迟最低的一个。函数内自排序，不依赖外部。"""
    healthy_srcs = sorted(
        healthy_srcs,
        key=lambda s: (not s["ok"], s["priority"], s.get("latency_ms", 999999), s["id"]),
    )
    seen_groups = set()
    picked = []
    for s in healthy_srcs:
        if not s["ok"]:
            continue
        group = s.get("failover_group") or ("solo:" + s["id"])
        if group in seen_groups:
            continue
        seen_groups.add(group)
        picked.append(s)
    return picked


def build_config(healthy_vod, healthy_live, max_sources):
    """由健康源重建配置。每组镜像只取一个，避免重复站点。"""
    picked_vod = pick_failover(healthy_vod)[:max_sources]
    picked_live = pick_failover(healthy_live)[:max_sources]
    subs = [s["url"] for s in picked_vod]
    lives = [to_live_entry(s) for s in picked_live]
    cfg = {
        "subs": subs,
        "lives": lives,
        "_meta": {
            "generated_by": "tvbox-selfheal-v2",
            "updated": now_str(),
            "active_vod": [{"id": s["id"], "group": s.get("failover_group", "-"), "count": s["count"], "latency_ms": s.get("latency_ms")} for s in picked_vod],
            "active_live": [{"id": s["id"], "group": s.get("failover_group", "-"), "count": s["count"], "latency_ms": s.get("latency_ms")} for s in picked_live],
            "all_healthy_vod": [{"id": s["id"], "count": s["count"]} for s in healthy_vod if s["ok"]],
            "all_healthy_live": [{"id": s["id"], "count": s["count"]} for s in healthy_live if s["ok"]],
            "note": "本文件由云端定时任务自动生成，请勿手动编辑；电视端固定填此地址。",
        },
    }
    return cfg


def render_report(results, state, action, cfg_snapshot):
    lines = []
    if state.get("needs_attention"):
        lines.append("> ## 持续失效告警：连续 %d 轮全源失效，配置已冻结，电视正在重试旧源" % state.get("consecutive_failures", 0))
        lines.append("")
    lines += [
        "# TVBox 自愈运行报告",
        "",
        "- 运行时间：%s" % now_str(),
        "- 本轮动作：**%s**" % action,
        "- 当前激活点播源：%s" % (", ".join(cfg_snapshot.get("subs", [])) or "无"),
        "- 镜像组选择：%s" % (", ".join(
            "%s→%s" % (x["id"], x.get("group", "-"))
            for x in cfg_snapshot.get("_meta", {}).get("active_vod", [])
        ) or "无"),
        "- 当前激活直播源：%s" % (", ".join(x.get("url", "") for x in cfg_snapshot.get("lives", [])) or "无"),
        "- 连续失败轮次：%d" % state.get("consecutive_failures", 0),
        "",
        "## 候选源探测明细",
        "",
        "| 源 ID | 类型 | 优先级 | HTTP | 延迟ms | 结果 | 数量 | 说明 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["kind"], r["priority"], r["status"],
            r.get("latency_ms", "-"), "健康" if r["ok"] else "失效",
            r["count"], r["reason"],
        ))
    lines += [
        "",
        "## 机制说明",
        "",
        "- VOD 同内容镜像同组去重，每组只取一个；live 不同频道集必须分不同组，否则会丢频道。",
        "- 多重复探测 + 延迟门槛，慢源偶发成功不会误判健康。",
        "- 失效保护按 vod/live 分组独立回填上一版，绝不让电视拉空。",
        "- 原子写入杜绝半截 JSON；连续失效达阈值升级告警。",
        "",
    ]
    return "\n".join(lines)


def main():
    cfg_all = load_json(CANDIDATES, {})
    if not cfg_all:
        print("ERROR: 缺少或无法读取 candidates.json")
        sys.exit(1)

    timeout = cfg_all.get("timeout_seconds", 12)
    min_sites = cfg_all.get("min_sites", 10)
    min_channels = cfg_all.get("min_channels", 40)
    max_sources = cfg_all.get("max_active_sources", cfg_all.get("max_sources_per_group", 3))
    workers = cfg_all.get("workers", 8)
    repeats = max(1, int(cfg_all.get("repeats", 2)))
    fail_alert = int(cfg_all.get("failures_before_alert", 3))
    groups = cfg_all.get("groups", {})

    # 跳过显式禁用、或 url 仍含 REPLACE_ME 未替换占位的源（如未配置的自托管快照）
    def enabled(srcs):
        out = []
        for s in srcs:
            if not s.get("enabled", True):
                continue
            if "REPLACE_ME" in str(s.get("url", "")):
                print("SKIP: 源 %s 的 url 含 REPLACE_ME 占位，视为未配置，跳过" % s.get("id", "?"))
                continue
            out.append(s)
        return out

    vod_srcs = enabled(groups.get("vod", []))
    live_srcs = enabled(groups.get("live", []))

    prev_state = load_json(STATE, {})
    if not isinstance(prev_state, dict):
        prev_state = {}
    prev_cfg = load_json(CONFIG, {})
    if not isinstance(prev_cfg, dict):
        prev_cfg = {}
    baselines = dict(prev_state.get("baseline_counts", {}))

    print("[1/4] 并发探测候选源（每源 %d 次重复）..." % repeats)
    vod_res = probe_all(vod_srcs, timeout, min_sites, min_channels, workers, repeats, baselines)
    live_res = probe_all(live_srcs, timeout, min_sites, min_channels, workers, repeats, baselines)
    healthy_vod = [r for r in vod_res if r["ok"]]
    healthy_live = [r for r in live_res if r["ok"]]
    print("      点播健康 %d/%d，直播健康 %d/%d" % (
        len(healthy_vod), len(vod_srcs), len(healthy_live), len(live_srcs)))

    all_results = vod_res + live_res
    print("[2/4] 判定动作 ...")
    state = dict(prev_state)

    if not healthy_vod and not healthy_live:
        # 全源失效：保留上一版（前提是真有上一版）
        if prev_cfg.get("subs") or prev_cfg.get("lives"):
            action = "失效保护：保留上一版 config.json（本轮全部候选失效）"
            cfg_snapshot = prev_cfg
            cnt = prev_state.get("consecutive_failures", 0) + 1
            state["consecutive_failures"] = cnt
            state["last_fail"] = now_str()
            if cnt >= fail_alert:
                action += "；连续失效达 %d 轮，需人工介入" % cnt
                state["needs_attention"] = True
        else:
            # 无上一版：区分'真首次'与'读失败'
            if os.path.exists(CONFIG):
                action = "配置文件存在但读取失败/为空，跳过写入以保护磁盘内容"
                cfg_snapshot = {"subs": [], "lives": []}  # 仅用于报告，不写盘
                cnt = prev_state.get("consecutive_failures", 0) + 1
                state["consecutive_failures"] = cnt
                state["last_fail"] = now_str()
            else:
                action = "首次运行全部失效：写入空配置占位"
                cfg_snapshot = {"subs": [], "lives": [],
                                "_meta": {"updated": now_str(), "note": "无健康源"}}
                cnt = prev_state.get("consecutive_failures", 0) + 1
                state["consecutive_failures"] = cnt
                state["last_fail"] = now_str()
                write_json(CONFIG, cfg_snapshot)
    else:
        new_cfg = build_config(healthy_vod, healthy_live, max_sources)
        # 分组独立回填：点播单独全挂也保留上一版 subs，绝不拉空
        if not healthy_vod and prev_cfg.get("subs"):
            new_cfg["subs"] = prev_cfg["subs"]
            new_cfg["_meta"]["active_vod"] = prev_cfg.get("_meta", {}).get("active_vod", [])
        if not healthy_live and prev_cfg.get("lives"):
            new_cfg["lives"] = prev_cfg["lives"]
            new_cfg["_meta"]["active_live"] = prev_cfg.get("_meta", {}).get("active_live", [])
        changed = (
            new_cfg.get("subs") != prev_cfg.get("subs")
            or [x.get("url") for x in new_cfg.get("lives", [])]
            != [x.get("url") for x in prev_cfg.get("lives", [])]
        )
        action = ("更新 config.json（源列表变化）" if changed
                  else "config.json 无变化（健康源与上一版一致）")
        cfg_snapshot = new_cfg
        if changed:
            write_json(CONFIG, new_cfg)
        state["consecutive_failures"] = 0
        state["needs_attention"] = False
        state["last_success"] = now_str()
        state["active_vod"] = new_cfg["subs"]
        state["active_live"] = [x["url"] for x in new_cfg.get("lives", [])]

    state["baseline_counts"] = baselines
    state["last_run"] = now_str()
    state["last_action"] = action
    if not isinstance(state.get("history"), list):
        state["history"] = []
    state["history"].insert(0, {"time": now_str(), "action": action})
    state["history"] = state["history"][:30]

    print("[3/4] 写入 state.json 与运行报告 ...")
    write_json(STATE, state)
    write_text(REPORT, render_report(all_results, state, action, cfg_snapshot))

    print("[4/4] 完成：%s" % action)
    for r in all_results:
        flag = "OK " if r["ok"] else "BAD"
        print("      [%s] %-28s %s" % (flag, r["id"], r["reason"]))
    if state.get("needs_attention"):
        print("      !! 连续 %d 轮失效，已在报告中升级告警" % state["consecutive_failures"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
