# -*- coding: utf-8 -*-
"""本机设置（目前只有「自动检查更新」和上次检查结果的缓存）。

刻意用 JSON 文件而不是塞进 SQLite：这些是**这台机器/这个部署**的偏好，不属于
某个考试，也不需要事务；放 `data/` 下跟库一起备份就够了。

写入用「临时文件 + os.replace」——`os.replace` 在 Windows 上也是原子的，
否则关机时正好在写就会留下一个半截的 JSON，下次启动读不出来。
"""
import json
import os

DEFAULTS = {
    'auto_check_update': True,   # 打开界面时自动查一次新版本
    'last_check': 0,             # 上次检查的 unix 时间戳，0 = 从没查过
    'last_result': None,         # 上次的检查结果（update.check 的返回结构）
}

# 「自动检查」的最短间隔：6 小时。不是省流量，是不想把 GitHub 当轮询靶子 ——
# 一个班几十号人开着页面，每人刷新一次就去打一次 API 是会被限流的。
CHECK_INTERVAL = 6 * 3600

_BOOL_KEYS = ('auto_check_update',)


class Settings:
    """`<data>/settings.json` 的读写。读失败一律退回默认值，绝不因此起不来。"""

    def __init__(self, path):
        self.path = path
        self._data = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------ 读

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            return self._data
        except Exception:  # noqa: BLE001 —— 文件坏了就当没有，别让服务起不来
            return self._data
        if isinstance(raw, dict):
            for k in DEFAULTS:
                if k in raw:
                    self._data[k] = raw[k]
        return self._data

    def get(self):
        return dict(self._data)

    # ------------------------------------------------------------ 写

    def patch(self, body):
        """只接受白名单里的键，非法值直接丢弃（外部输入不配改坏配置）。"""
        if not isinstance(body, dict):
            raise ValueError('设置必须是一个对象')
        changed = False
        for k in _BOOL_KEYS:
            if k in body:
                self._data[k] = bool(body[k])
                changed = True
        for k in ('last_check', 'last_result'):
            if k in body:
                self._data[k] = body[k]
                changed = True
        if changed:
            self.save()
        return self.get()

    def save(self):
        tmp = self.path + '.tmp'
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001 —— 设置存不下来不该影响识别
            try:
                os.remove(tmp)
            except OSError:
                pass
        return self._data
