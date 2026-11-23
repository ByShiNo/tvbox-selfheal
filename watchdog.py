#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外部 watchdog（心跳检测 + 自恢复）。

解决的问题：GitHub Actions 公开仓 60 天闲置会自动禁用 schedule，且不会自恢复；
workflow 自身无法恢复自身。所以心跳必须在 GitHub 之外跑。

部署：放到 cron-job.org / 腾讯云 SCF / 任意常开的云函数，每 3 小时跑一次。
依赖：仅标准库。可选装 gh CLI 做自恢复（没装也能告警）。

用法：
  python watchdog.py \
    --config-url https://raw.githubusercontent.com/<user>/<repo>/main/config.json \
    --repo <user>/<repo> \
    --workflow heal.yml \
    --bark-key <你的Bark Key>        # 可选，告警推送
    --enable-key <你的GitHub Token>  # 可选，用于 gh workflow enable 自恢复

告警渠道二选一：Bark（--bark-key）或 Server酱（--serverchan-key）。都不填则只打印。
"""
import argparse
import datetime
import json
import subprocess
import sys
import urllib.request

MAX_AGE_HOURS = 8   # config.json 超过 8 小时没更新就告警（cron 3 小时 + 余量）


def log(m):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), m), flush=True)


def get_updated(config_url):
    req = urllib.request.Request(config_url, headers={"User-Agent": "TVBox-Watchdog/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return data.get("_meta", {}).get("updated", "")


def age_hours(updated_str):
    # 形如 2026-11-23 18:24:12 +0800
    dt = datetime.datetime.strptime(updated_str, "%Y-%m-%d %H:%M:%S %z")
    now = datetime.datetime.now(dt.tzinfo)
    return (now - dt).total_seconds() / 3600.0


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
    """尝试自恢复：重新启用被禁用的 workflow。需要 gh CLI + token。"""
    if not token:
        log("未提供 --enable-key，跳过自恢复")
        return
    cmd = ["gh", "api", "-X", "PUT",
           "repos/%s/actions/workflows/%s/enable" % (repo, workflow)]
    env = None
    try:
        subprocess.run(cmd, check=True, capture_output=True,
                       env={**__import__("os").environ, "GH_TOKEN": token})
        log("已尝试重新启用 workflow %s" % workflow)
    except Exception as e:
        log("自恢复失败（需本机有 gh CLI 且 token 有 write 权限）：%s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-url", required=True)
    ap.add_argument("--repo", default="", help="形如 user/repo，用于自恢复")
    ap.add_argument("--workflow", default="heal.yml")
    ap.add_argument("--bark-key", default="")
    ap.add_argument("--serverchan-key", default="")
    ap.add_argument("--enable-key", default="", help="GitHub Token，用于 gh workflow enable 自恢复")
    args = ap.parse_args()

    try:
        updated = get_updated(args.config_url)
    except Exception as e:
        msg = "TVBox watchdog：连 config.json 都拉不到，可能仓库转私有或网络故障：%s" % e
        log(msg)
        notify(msg, args.bark_key, args.serverchan_key)
        if args.repo:
            try_enable(args.repo, args.workflow, args.enable_key)
        sys.exit(1)

    if not updated:
        log("config.json 无 _meta.updated 字段，无法判断心跳")
        sys.exit(0)

    age = age_hours(updated)
    log("config.json 年龄 %.1f 小时（阈值 %d）" % (age, MAX_AGE_HOURS))
    if age > MAX_AGE_HOURS:
        msg = "TVBox 自愈疑似停摆：config.json 已 %.1f 小时未更新，请检查 Actions" % age
        log(msg)
        notify(msg, args.bark_key, args.serverchan_key)
        if args.repo:
            try_enable(args.repo, args.workflow, args.enable_key)
        sys.exit(1)
    log("心跳正常")


if __name__ == "__main__":
    main()
