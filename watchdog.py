#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外部 watchdog（心跳检测 + 自恢复）。

解决的问题：GitHub Actions 公开仓 60 天闲置会自动禁用 schedule，且不会自恢复；
workflow 自身无法恢复自身。所以心跳必须在 GitHub 之外跑（cron-job.org / 腾讯云 SCF）。

心跳源选择（按可靠性排序）：
  1) GitHub Actions API：最近一次 workflow run 的时间 —— 最真实，直接反映 workflow 是否在跑。
     传 --repo user/name 即启用（需 token 才能读私有，公开仓 anonymous 也行但限流）。
  2) state.json 的 last_run —— heal.py 每轮都写，公开 raw 可匿名拉，稳定。
  3) config.json 的 _meta.updated —— 只在源列表变化时更新，健康无变化时不更新，
     因此【不能单独当心跳】，仅作参考。

依赖：仅标准库。自恢复需 gh CLI + 有 write 权限的 token。

用法：
  python watchdog.py \
    --state-url https://raw.githubusercontent.com/<user>/<repo>/main/state.json \
    --config-url https://raw.githubusercontent.com/<user>/<repo>/main/config.json \
    --repo <user>/<repo> --workflow heal.yml \
    --token <ghp_xxx> \
    --bark-key <Bark Key>            # 可选，告警推送
    --serverchan-key <Server酱 key>  # 可选，告警推送

  说明：--repo + --token 时优先用 Actions API 心跳；否则用 --state-url；
        两者都没有才退回 --config-url（不推荐）。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

MAX_AGE_HOURS = 8   # 超过 8 小时没动静就告警（cron 3 小时 + 余量）


def log(m):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), m), flush=True)


def http_json(url, token="", timeout=20):
    headers = {"User-Agent": "TVBox-Watchdog/2.0", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_age(updated_str):
    """把 '2026-11-23 18:24:12 +0800' 或 ISO '2026-11-23T11:23:04Z' 转成年龄小时。"""
    if not updated_str:
        return None
    s = updated_str.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        elif "T" in s and "+" in s:
            dt = datetime.datetime.fromisoformat(s)
        else:
            dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except Exception:
        return None
    now = datetime.datetime.now(dt.tzinfo)
    return (now - dt).total_seconds() / 3600.0


def heartbeat_from_actions(repo, workflow, token):
    """GitHub Actions 最近一次 run 的创建时间 —— 最可靠心跳。"""
    url = "https://api.github.com/repos/%s/actions/workflows/%s/runs?per_page=1" % (repo, workflow)
    data = http_json(url, token)
    runs = data.get("workflow_runs", [])
    if not runs:
        return None, "Actions 无运行记录"
    r = runs[0]
    return r.get("created_at"), "%s / %s" % (r.get("status"), r.get("conclusion"))


def heartbeat_from_state(state_url):
    data = http_json(state_url)
    return data.get("last_run", ""), "state.json"


def heartbeat_from_config(config_url):
    data = http_json(config_url)
    return data.get("_meta", {}).get("updated", ""), "config.json（仅变化时更新，仅供参考）"


def notify(msg, bark_key, sc_key):
    if bark_key:
        try:
            urllib.request.urlopen(
                "https://api.day.app/%s/%s" % (bark_key, urllib.parse.quote(msg)), timeout=10
            )
            log("已推送 Bark")
        except Exception as e:
            log("Bark 推送失败：%s" % e)
    if sc_key:
        try:
            urllib.request.urlopen(
                "https://sc.ftqq.com/%s.send?text=%s" % (sc_key, urllib.parse.quote(msg)), timeout=10
            )
            log("已推送 Server酱")
        except Exception as e:
            log("Server酱推送失败：%s" % e)


def try_enable(repo, workflow, token):
    """自恢复：重新启用被禁用的 workflow。需 token 有 actions:write 权限。"""
    if not (repo and token):
        log("未提供 --repo/--token，跳过自恢复")
        return
    url = "https://api.github.com/repos/%s/actions/workflows/%s/enable" % (repo, workflow)
    req = urllib.request.Request(url, data=b"", method="PUT", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "TVBox-Watchdog/2.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log("已尝试重新启用 workflow %s（HTTP %d）" % (workflow, r.status))
    except Exception as e:
        log("自恢复失败（token 需 actions:write 权限）：%s" % e)


def trigger_workflow(repo, workflow, token):
    """自恢复第二步：补跑一次 workflow（enable 之后立即触发验证）。"""
    if not (repo and token):
        return
    url = "https://api.github.com/repos/%s/actions/workflows/%s/dispatches" % (repo, workflow)
    body = json.dumps({"ref": "main"}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "TVBox-Watchdog/2.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log("已触发 workflow 补跑（HTTP %d）" % r.status)
    except Exception as e:
        log("触发 workflow 失败：%s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-url", default="", help="config.json raw 地址（兜底心跳）")
    ap.add_argument("--state-url", default="", help="state.json raw 地址（推荐心跳）")
    ap.add_argument("--repo", default="", help="user/repo，配合 --token 用 Actions API 心跳 + 自恢复")
    ap.add_argument("--workflow", default="heal.yml")
    ap.add_argument("--token", default="", help="GitHub token（读 Actions + 自恢复）")
    ap.add_argument("--bark-key", default="")
    ap.add_argument("--serverchan-key", default="")
    ap.add_argument("--max-age", type=float, default=MAX_AGE_HOURS)
    args = ap.parse_args()

    updated = None
    source = ""
    extra = ""

    # 心跳优先级：Actions API > state.json > config.json
    if args.repo:
        try:
            updated, extra = heartbeat_from_actions(args.repo, args.workflow, args.token)
            source = "GitHub Actions API"
        except Exception as e:
            log("Actions API 心跳读取失败：%s；尝试 state.json" % e)
    if not updated and args.state_url:
        try:
            updated, source = heartbeat_from_state(args.state_url)
        except Exception as e:
            log("state.json 心跳读取失败：%s；尝试 config.json" % e)
    if not updated and args.config_url:
        try:
            updated, source = heartbeat_from_config(args.config_url)
        except Exception as e:
            msg = "TVBox watchdog：所有心跳源都拉不到，仓库可能转私有或网络故障：%s" % e
            log(msg)
            notify(msg, args.bark_key, args.serverchan_key)
            if args.repo:
                try_enable(args.repo, args.workflow, args.token)
                trigger_workflow(args.repo, args.workflow, args.token)
            sys.exit(1)

    if not updated:
        log("未能取得任何心跳时间，无法判断，退出")
        sys.exit(0)

    age = parse_age(updated)
    if age is None:
        log("心跳时间格式无法解析：%s" % updated)
        sys.exit(0)
    log("心跳源=%s | 时间=%s | 年龄=%.1f 小时（阈值 %.1f）%s" % (
        source, updated, age, args.max_age, (" | " + extra) if extra else ""))

    if age > args.max_age:
        msg = "TVBox 自愈疑似停摆：%s 已 %.1f 小时未更新（阈值 %.1f），请检查 Actions" % (
            source, age, args.max_age)
        log(msg)
        notify(msg, args.bark_key, args.serverchan_key)
        if args.repo:
            try_enable(args.repo, args.workflow, args.token)
            trigger_workflow(args.repo, args.workflow, args.token)
        sys.exit(1)
    log("心跳正常")


if __name__ == "__main__":
    main()
