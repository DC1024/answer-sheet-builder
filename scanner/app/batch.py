# 批量上传：解包 zip / 归组多页 / 解析名单 / 匹配学生。
#
# 目标：一次丢一个班的扫描件进来，而不是一份一份传。
# 关键约定是「文件名/目录名里带考号」：
#     2026010234/正面.png   2026010234/反面.png
#     2026010234_1.png      2026010234_2.png
#     2026010234.png
# 目录名优先于文件名（学生按目录分文件夹是最省事的做法）。
# 解析不出考号时退回用文件名当标识，这样原来的单份用法照旧能用。
import csv
import io
import os
import re
import zipfile

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff', '.gif'}
ROSTER_EXT = {'.csv', '.tsv', '.txt'}

# 打包工具塞进来的垃圾
SKIP_DIRS = {'__macosx', '.git', '.idea'}
SKIP_NAMES = {'.ds_store', 'thumbs.db', 'desktop.ini'}

# 考号：4~20 位数字。太短容易误伤（如 "1.png"），太长不是考号。
SID_RE = re.compile(r'(\d{4,20})')

# 页序提示。键是**小写**，中文原样。裸数字按「第 N 页」处理（1 起算），上限防误伤。
PAGE_HINTS = {
    '正': 0, '正面': 0, '前': 0, '前页': 0, '首页': 0, '上': 0,
    'front': 0, 'f': 0, 'a': 0, 'p1': 0,
    '反': 1, '反面': 1, '后': 1, '后页': 1, '背': 1, '背面': 1, '下': 1,
    'back': 1, 'r': 1, 'b': 1, 'p2': 1,
}
MAX_PAGE_NO = 20                      # 裸数字超过它就不当页号（避开年份、编号）
PAGE_ZH = re.compile(r'第\s*(\d+)\s*[页版面]')

# 名单表头别名（顺序即优先级：越靠前越优先命中）
RID_KEYS = ('考号', '准考证号', '考生号', '学号', '座号', '编号', 'id', 'sid', 'number', 'no')
NAME_KEYS = ('姓名', '学生姓名', '名字', 'name')
CLASS_KEYS = ('班级', '行政班', '班级名称', '班', 'class')


class BatchError(Exception):
    pass


def _read_text(raw):
    """中文 Excel 导出的 CSV 常见是 GBK —— utf-8 解不开就退回 GBK。"""
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', 'replace')


def _natkey(s):
    """自然排序：s2 排在 s10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


# 服务端也要用（导出按考号排序），给个不带下划线的名字
natkey = _natkey


def _skip(relpath):
    parts = [p for p in relpath.replace('\\', '/').split('/') if p]
    for p in parts:
        if p.lower() in SKIP_DIRS or p.lower() in SKIP_NAMES:
            return True
        if p.startswith('._'):       # macOS 资源分叉文件
            return True
    return False


def _hint_from(text):
    """从一段文本里找页序提示，返回 0 基页码；找不到返回 None。

    识别顺序：`第2页` 这种中文写法 → 命名页词（正面/反面/p2/front…）→ 裸数字。
    裸数字按「第 N 页」处理，所以 `_2`→1、`_10`→9；超过 MAX_PAGE_NO 的不当页号
    （避免把 `_2023` 这类年份当成第 2023 页）。取**最后一个**命中项，后缀更具体。
    """
    if not text:
        return None
    m = PAGE_ZH.search(text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= MAX_PAGE_NO:
            return n - 1
    toks = [t for t in re.split(r'[^0-9A-Za-z\u4e00-\u9fff]+', text) if t]
    for tok in reversed(toks):
        key = tok if re.search(r'[\u4e00-\u9fff]', tok) else tok.lower()
        if key in PAGE_HINTS:
            return PAGE_HINTS[key]
        if tok.isdigit():
            n = int(tok)
            if 1 <= n <= MAX_PAGE_NO:
                return n - 1
    return None


def parse_entry(relpath):
    """从相对路径解析 (考号, 页序提示)。

    支持： 2026010234/正面.png · 2026010234_1.png · 2026010234.png · 张伟明-2026010234.png
    解析不出考号时退回文件名整体当标识（保持「一份一份传」的旧用法可用）。
    """
    rel = relpath.replace('\\', '/')
    parts = [p for p in rel.split('/') if p]
    stem = os.path.splitext(parts[-1])[0] if parts else ''
    dirs = parts[:-1]

    sid, page = None, None

    # 1) 目录名优先：从最深的目录往外找第一个带数字串的
    for d in reversed(dirs):
        m = SID_RE.search(d)
        if m:
            sid = m.group(1)
            page = _hint_from(d.replace(m.group(1), '', 1))
            break

    if sid is None:
        m = SID_RE.search(stem)
        if m:
            # 取最后一段数字串当考号（"张伟明-2026010234" 中的才对）
            m = list(SID_RE.finditer(stem))[-1]
            sid = m.group(1)
            page = _hint_from(stem[:m.start()]) or _hint_from(stem[m.end():])
        else:
            sid = stem or os.path.splitext(parts[-1])[0]
            page = _hint_from(stem)
    else:
        # 考号来自目录，页提示看文件名
        page = page if page is not None else _hint_from(stem)

    return sid, page


def unpack(uploads):
    """展开上传内容。uploads: [(relpath, filename, data)]。

    zip 就地展开（保留内部路径，嵌套 zip 也展开）；其余按图片/名单分类。
    返回 (images, rosters, zip_count)：
      images  = [(relpath, filename, data)]
      rosters = [(relpath, text)]
    """
    images, rosters, zips = [], [], 0

    def handle(relpath, filename, data):
        nonlocal zips
        if _skip(relpath):
            return
        low = filename.lower()
        if low.endswith('.zip') or data[:4] == b'PK\x03\x04':
            zips += 1
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as e:
                raise BatchError(f'{filename} 不是有效的 zip：{e}')
            for info in zf.infolist():
                if info.is_dir():
                    continue
                inner = info.filename
                base = os.path.basename(inner)
                if not base:
                    continue
                payload = zf.read(info)
                handle(inner, base, payload)
            return
        ext = os.path.splitext(low)[1]
        if ext in IMAGE_EXT:
            images.append((relpath, filename, data))
        elif ext in ROSTER_EXT and data:
            rosters.append((relpath, _read_text(data)))

    for relpath, filename, data in uploads:
        handle(relpath, filename, data)

    return images, rosters, zips


def group(images):
    """按考号归组并按页序排好。

    返回 [{sid, pages: [{relpath, name, data, page}], issues: [...]}]，按考号自然序排列。
    「同一考号出现在不同目录」会被标为可疑重复 —— 同一目录下多文件是正常的多页，
    跨目录同名多半是重复上传或撞号。

    `issues` 是这一阶段就成立的问题，同时留一份到 `baseIssues`：`match()` 每次都从
    `baseIssues` 重建问题列表，否则反复套名单会让问题越滚越多。
    """
    buckets, dirs = {}, {}
    for relpath, filename, data in images:
        sid, page = parse_entry(relpath)
        buckets.setdefault(sid, []).append(
            {'relpath': relpath, 'name': os.path.basename(relpath), 'data': data, 'page': page})
        rel = relpath.replace('\\', '/')
        dirs.setdefault(sid, set()).add(rel.rsplit('/', 1)[0] if '/' in rel else '')

    students = []
    for sid, pages in buckets.items():
        issues = []
        if len(dirs[sid]) > 1:
            issues.append('同一考号出现在多个目录（可能是重复上传或撞号）：'
                          + '、'.join(sorted(d for d in dirs[sid] if d))[:80])
        # 有页提示的按提示排在前；没有的按文件名自然序接在后面，保持相对顺序
        pages.sort(key=lambda p: (p['page'] if p['page'] is not None else 99, _natkey(p['name'])))
        for i, p in enumerate(pages):
            if p['page'] is None:
                p['page'] = i
        students.append({'sid': sid, 'pages': pages, 'issues': issues,
                         'baseIssues': list(issues), 'dirs': sorted(dirs[sid])})
    students.sort(key=lambda s: _natkey(s['sid']))
    return students


def _clean(s):
    """去掉 BOM 和首尾空白 —— BOM 混进单元格会让考号匹配不上。"""
    return str(s).replace('\ufeff', '').strip()


def parse_roster(text, delim=None):
    """解析名单。表头别名宽松匹配，支持逗号 / 制表符 / 分号分隔。

    返回 (roster, columns)：roster = {考号: {'name':..., 'cls':...}}
    """
    if not text or not text.strip():
        return {}, {}

    sample = text[:4096]
    if delim is None:
        delim = max((',', '\t', ';', '|'), key=sample.count)

    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return {}, {}

    # 找表头行：前 5 行里第一个能识别出「考号」列的行
    head_i, cols = None, {}
    for i, row in enumerate(rows[:5]):
        c = _map_columns(row)
        if c.get('sid') is not None:
            head_i, cols = i, c
            break
    if head_i is None:
        raise BatchError('名单里找不到「考号/学号/准考证号」列，请检查表头')

    roster = {}
    for row in rows[head_i + 1:]:
        def cell(key):
            j = cols.get(key)
            return _clean(row[j]) if j is not None and j < len(row) else ''
        sid = cell('sid')
        if not sid:
            continue
        roster[sid] = {'name': cell('name'), 'cls': cell('cls')}
    return roster, {k: _clean(rows[head_i][v]) if v < len(rows[head_i]) else ''
                    for k, v in cols.items()}


def _map_columns(row):
    """把一行表头映射成 {'sid':i,'name':j,'cls':k}"""
    cells = [_clean(c).lower().replace('\u3000', '') for c in row]
    out = {}

    def find(keys):
        # 先精确匹配，再模糊包含 —— 避免「班级排名」被当成「班级」
        for k in keys:
            for i, c in enumerate(cells):
                if c == k:
                    return i
        for k in keys:
            for i, c in enumerate(cells):
                if k in c:
                    return i
        return None

    out['sid'] = find(RID_KEYS)
    out['name'] = find(NAME_KEYS)
    out['cls'] = find(CLASS_KEYS)
    return out


def find_roster(rosters):
    """从 zip 里带的候选名单文件里挑一个 —— 行数最多的那个最像名单。"""
    best = None
    for relpath, text in rosters:
        try:
            roster, cols = parse_roster(text)
        except BatchError:
            continue
        if roster and (best is None or len(roster) > len(best[0])):
            best = (roster, cols, relpath)
    return best


def match(students, roster, overrides=None):
    """把名单信息贴到学生上，并标出需要人工确认的问题。

    overrides: {sid: {'name':.., 'cls':..}} —— 人工补录优先于名单。
    问题列表每次从 `baseIssues`（归组阶段）+ `pageIssues`（识别阶段）重建，所以
    同一份数据可以反复调用（老师补录姓名后重新套名单），不会把问题越堆越多。
    返回 (students, warnings)。
    """
    overrides = overrides or {}
    warnings = []

    for stu in students:
        sid = stu['sid']
        info = dict(roster.get(sid) or {})
        info.update({k: v for k, v in (overrides.get(sid) or {}).items() if v})
        stu['name'] = info.get('name') or ''
        stu['cls'] = info.get('cls') or ''
        stu['issues'] = list(stu.get('baseIssues') or []) + list(stu.get('pageIssues') or [])
        stu['manual'] = bool(overrides.get(sid))

        if not roster:
            stu['matched'] = None                       # 没导名单，谈不上匹配
        elif sid in roster or sid in overrides:
            stu['matched'] = True
            if not stu['name']:
                stu['issues'].append('名单里这一行没填姓名')
        else:
            stu['matched'] = False
            stu['issues'].append('考号不在名单里')

        if not SID_RE.fullmatch(sid):
            stu['issues'].append('未能从文件名解析出考号，已用文件名当标识')

        if len(stu['pages']) > 1:
            hints = [p['page'] for p in stu['pages']]
            if len(set(hints)) != len(hints):
                stu['issues'].append('多页被排到同一页码，请确认页序')

    dup = [s['sid'] for s in students if any('重复' in i for i in s['issues'])]
    if dup:
        warnings.append(f'疑似重复上传：{", ".join(sorted(set(dup)))}')

    bad = [s['sid'] for s in students if s['matched'] is False]
    if bad:
        warnings.append(f'有 {len(bad)} 个考号不在名单里：{", ".join(map(str, bad[:8]))}'
                        + ('…' if len(bad) > 8 else ''))
    if roster:
        read = {s['sid'] for s in students}
        missing = [k for k in roster if k not in read]
        if missing:
            warnings.append(f'名单里有 {len(missing)} 人没交卷（或没上传）：'
                            f'{", ".join(map(str, missing[:8]))}' + ('…' if len(missing) > 8 else ''))
    return students, warnings


def merge_answers(pages):
    """把一份卷子多页的逐题结果合并成一套答案。

    返回 (answers, conflicts)：answers = {题号: {answer, flag, ...}}
    """
    answers, conflicts = {}, []
    for pg in pages:
        for q in pg.get('questions') or []:
            no = q['no']
            if no in answers and answers[no].get('answer') != q.get('answer'):
                conflicts.append(no)
            answers[no] = {'answer': q.get('answer'), 'flag': q.get('flag'),
                           'best': q.get('best'), 'second': q.get('second'),
                           'ratios': q.get('ratios'), 'inks': q.get('inks')}
    answers = {k: answers[k] for k in sorted(answers)}
    return answers, sorted(set(conflicts))
