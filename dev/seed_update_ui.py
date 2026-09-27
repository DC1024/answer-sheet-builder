# 自更新面板 UI 联调的种子：起一个真 Flask 服务，交给 dev/verify_update_ui.cjs 点。
#
# 和 seed_subjective_ui.py 同一个套路，但**不需要造考试数据** —— 这块 UI 只关心
# 设置页上的版本号与更新按钮，所以起服务 + 建管理员就够了。所有 /api/update*
# 的响应在 node 侧用 route 拦截伪造（见 verify_update_ui.cjs），因为要确定性
# 地演「重启中 / 起来了还是旧版本 / 起来了是新版本」这三种时序。
#
# 用法：
#   scanner/.venv/Scripts/python.exe dev/seed_update_ui.py
#   环境变量：PORT（默认 8197）、ASB_DATA / ASB_DB
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scanner'))

CACHE = os.path.join(HERE, '.cache')
os.makedirs(CACHE, exist_ok=True)
DATA = os.environ.get('ASB_DATA') or tempfile.mkdtemp(prefix='upd-ui-data-', dir=CACHE)
PORT = int(os.environ.get('PORT') or 8197)

os.makedirs(DATA, exist_ok=True)
os.environ['ASB_DATA'] = DATA
os.environ['ASB_DB'] = os.path.join(DATA, 'asb.db')

from app import server   # noqa: E402

USER, PW = 'uiadmin', 'uitest12345'


def main():
    c = server.app.test_client()
    r = c.post('/api/setup', json={'username': USER, 'password': PW})
    if r.status_code not in (200, 409):
        raise SystemExit('建管理员失败：%s %s' % (r.status_code, r.data[:200]))
    print('version=%s data=%s' % (server.APP_VERSION, DATA), flush=True)
    sys.stdout.flush()
    # 关掉自动检查，免得 seed 自己去打 GitHub（内网/沙箱里会拖慢启动）
    server.SETTINGS.patch({'auto_check_update': False, 'auto_install': False})
    server.app.run(host='127.0.0.1', port=PORT, threaded=True, debug=False,
                   use_reloader=False)


if __name__ == '__main__':
    main()