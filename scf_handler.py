#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯云 SCF 入口：包装 watchdog.py 的判活逻辑。
把本文件和 watchdog.py 一起上传到 SCF（Python 3.9+），入口函数 scf_handler.main_handler。
配置下面环境变量即可，无需命令行参数。
"""
import os
import sys

import watchdog as wd


def main_handler(event=None, context=None):
    token = os.environ.get("GH_TOKEN", "")
    state_url = os.environ.get("STATE_URL", "")
    config_url = os.environ.get("CONFIG_URL", "")
    repo = os.environ.get("REPO", "ByShiNo/tvbox-selfheal")
    workflow = os.environ.get("WORKFLOW", "heal.yml")
    bark = os.environ.get("BARK_KEY", "")
    sc = os.environ.get("SERVERCHAN_KEY", "")
    max_age = float(os.environ.get("MAX_AGE_HOURS", "8"))

    updated, source, extra = None, "", ""
    if repo:
        try:
            updated, extra = wd.heartbeat_from_actions(repo, workflow, token)
            source = "GitHub Actions API"
        except Exception as e:
            wd.log("Actions API 心跳失败：%s，回退 state.json" % e)
    if not updated and state_url:
        try:
            updated, source = wd.heartbeat_from_state(state_url)
        except Exception as e:
            wd.log("state.json 心跳失败：%s，回退 config.json" % e)
    if not updated and config_url:
        updated, source = wd.heartbeat_from_config(config_url)

    if not updated:
        msg = "TVBox watchdog：所有心跳源都拉不到，请检查仓库/网络"
        wd.log(msg)
        wd.notify(msg, bark, sc)
        if repo:
            wd.try_enable(repo, workflow, token)
            wd.trigger_workflow(repo, workflow, token)
        return {"ok": False, "reason": msg}

    age = wd.parse_age(updated)
    wd.log("心跳源=%s | 时间=%s | 年龄=%.1fh%s" % (
        source, updated, age if age is not None else -1,
        (" | " + extra) if extra else ""))
    if age is None:
        return {"ok": True, "reason": "时间格式无法解析，跳过"}

    if age > max_age:
        msg = "TVBox 自愈停摆：%s 已 %.1fh 未更新，正在自恢复" % (source, age)
        wd.log(msg)
        wd.notify(msg, bark, sc)
        if repo:
            wd.try_enable(repo, workflow, token)
            wd.trigger_workflow(repo, workflow, token)
        return {"ok": False, "reason": msg}

    wd.log("心跳正常")
    return {"ok": True, "age_hours": round(age, 2), "source": source}
