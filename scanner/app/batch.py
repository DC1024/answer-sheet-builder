# 批量上传：解包 zip / 归组多页 / 解析名单 / 匹配学生。
#
# 目标：一次丢一个班的扫描件进来，而不是一份一份传。
#
# 身份来源有两层，**卷面优先**：
#   1) 答题卡上的考号填涂区（识别出来之后才知道）—— 见本文件末尾的 regroup()
#   2) 文件名/目录名里的考号（备选，且老师的命名习惯比想象中随意得多）：
#        2026010234/正面.png   2026010234/反面.png
#        2026010234_1.png      2026010234_2.png
#        2026010234.png
#      目录名优先于文件名。解析不出考号时退回用文件名当标识。
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
            # 记下「这一页的页码是文件名提示的，还是我们按顺序猜的」——
            # 多面模板 + 没有页序提示 = 可能在拿第 2 面的坐标去采第 1 面，必须提醒。
            p['hinted'] = p['page'] is not None
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
        stu['sidSuggest'] = list(stu.get('sidSuggest') or [])

        if not roster:
            stu['matched'] = None                       # 没导名单，谈不上匹配
        elif sid in roster or sid in overrides:
            stu['matched'] = True
            if not stu['name']:
                stu['issues'].append('名单里这一行没填姓名')
        else:
            stu['matched'] = False
            sug = suggest_sid(sid, roster)
            # 只有**唯一**候选才值得说出来。很多学校考号是连号的（…234/235/236），
            # 一个陌生的 237 会和其中好几个"只差一位" —— 那时候给建议纯粹是噪音。
            stu['sidSuggest'] = sug if len(sug) == 1 else []
            if len(sug) == 1:
                pos = [i + 1 for i, (a, b) in enumerate(zip(sug[0], str(sid))) if a != b]
                stu['issues'].append(
                    f'考号不在名单里；名单里 {sug[0]} 只差第 {pos[0]} 位'
                    f'（{str(sid)[pos[0] - 1]} → {sug[0][pos[0] - 1]}）—— 疑似涂错一位')
            else:
                stu['issues'].append('考号不在名单里')

        if not SID_RE.fullmatch(str(sid)):
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
    near = [(s['sid'], s['sidSuggest'][0]) for s in students if s.get('sidSuggest')]
    if near:
        warnings.append(f'其中 {len(near)} 份卷子的考号与名单里的人只差一位'
                        f'（{"、".join(f"{a}→{b}" for a, b in near[:4])}）—— '
                        f'先核对是涂错还是名单有误，再判分')
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


# ---------------------------------------------------------------- 卷面考号
#
# 文件名归组要求老师把文件命名成考号，现实里做不到（「不可能每个学生都发二维码」，
# 同理也不会有人专门去改 50 个文件名）。但答题卡上本来就印了考号填涂区 ——
# 识别完之后从卷面上把考号读回来，用它校正/补全分组。
#
# 这里只在**识别完之后**做，因为卷面考号必须先认出卷子才拿得到。

SID_HOLES_MAX = 2       # 卷面最多容忍几位没读出来（整格漏涂很常见，1~2 位可以靠名单补）

# sidSource → 给人看的一句话。老师说「这个考号哪来的」比看内部字段名直观。
SID_SOURCE_ZH = {
    'file': '文件名',
    'file-stem': '文件名（没解析出考号）',
    'sheet': '卷面填涂',
    'both': '文件名 + 卷面（一致）',
    'roster': '卷面 + 名单补全缺位',
    'conflict': '⚠ 文件名与卷面不一致',
    'sheet-partial': '⚠ 卷面有缺位',
}


def resolve_sid(text, roster):
    """考号里有几位没读出来时，用名单把洞补上。

    只有「名单里有且只有一个人符合」才敢补 —— 补错了就是把卷子记到别人名下，
    比留个洞让人来输糟得多。返回 (考号 or None, 全部候选)。
    """
    if '?' not in text or not roster:
        return None, []
    num = str(text)
    pat = re.compile(''.join('.' if c == '?' else re.escape(c) for c in num))
    hits = [str(k) for k in roster if len(str(k)) == len(num) and pat.match(str(k))]
    return (hits[0] if len(hits) == 1 else None), hits


def sheet_sids(pages):
    """汇总一份卷子各页读到的卷面考号。

    返回 (考号 or None, info)。`?` 表示那一位没读出来。
    只有「读出来的每一页都一致」才算数：同一个人两页读出两个考号，说明有东西错了，
    这时候猜哪一个都是错的一半，交给人工。
    """
    reads = [(p.get('sid') or {}).get('text') or '' for p in pages]
    reads = [t.strip() for t in reads if t and t.strip()]
    info = {'reads': reads, 'holes': 0, 'agree': True, 'why': ''}
    if not reads:
        info['why'] = '没有读到卷面考号（模板里没有考号填涂区，或这几页都没认出来）'
        return None, info
    uniq = sorted(set(reads))
    if len(uniq) > 1:
        info.update(agree=False, why='同一份卷子的不同页读出的考号不一样：' + '、'.join(uniq))
        return None, info
    text = uniq[0]
    info['holes'] = text.count('?')
    if info['holes'] > SID_HOLES_MAX:
        info['why'] = f'卷面考号只读出 {len(text) - info["holes"]}/{len(text)} 位，认不出是谁'
        return None, info
    return text, info


def _absorb(dst, src):
    """把 src 的页并进 dst（同一个考号被拆在几个分组里时）。"""
    dst['pages'] = list(dst.get('pages') or []) + list(src.get('pages') or [])
    dst['pages'].sort(key=lambda p: (p.get('page') if p.get('page') is not None else 99,
                                     _natkey(p.get('name') or '')))
    dst['dirs'] = sorted(set(dst.get('dirs') or []) | set(src.get('dirs') or []))
    extra = [i for i in (src.get('baseIssues') or []) if i not in (dst.get('baseIssues') or [])]
    dst['baseIssues'] = list(dst.get('baseIssues') or []) + extra
    dst['mergedFrom'] = list(dst.get('mergedFrom') or []) + \
        [str(src.get('fileSid') or src.get('sid'))] + list(src.get('mergedFrom') or [])
    # 页变了，答案就得重算 —— 合并后同题号可能撞车，正好在这儿报出来
    dst['answers'], conflicts = merge_answers([p for p in dst['pages'] if p.get('ok')])
    dst['conflicts'] = conflicts
    if conflicts:
        msg = '多页同一题号答案不一致：' + '、'.join(f'第{c}题' for c in conflicts[:10])
        if msg not in (dst.get('pageIssues') or []):
            dst['pageIssues'] = list(dst.get('pageIssues') or []) + [msg]
    dst['source'] = '、'.join(p['source'] for p in dst['pages'] if p.get('source'))


def regroup(students, roster=None):
    """用卷面读到的考号校正分组。原地改 students，返回新的列表（可能更短）。

    学校不给学生发二维码、也不会有人把 50 个文件改名成考号 —— 所以「卷面考号」才是
    主身份来源，文件名只是备选。但**不能自作主张**：把两份卷子并成一份、或者把卷子
    记到别人名下，都是不可逆的错。所以规则是：

      文件名里有可信的考号 + 卷面读到且一致 → 两边互证
      文件名里有可信的考号 + 卷面读到但不一致 → **保持原样**，两边都报出来让人确认
      文件名里没有可信考号 + 卷面读到 → 用卷面的（还能把散着传的多页并成一份）
      卷面有洞 → 名单里只有一个人符合才敢补，否则留着洞等人填
    """
    for stu in students:
        text, info = sheet_sids(stu['pages'])
        stu['sheetSid'] = text
        stu['sheetSidInfo'] = info
        stu['fileSid'] = str(stu.get('sid') or '')
        stu['sidSuggest'] = []
        # 「文件名里的数字是不是考号」要分清楚：IMG_0001 里的 0001 不是，
        # 2026010234_1.png 里的才是。前者如果被判成「另一个考号」，就会把卷面考号
        # 当成冲突而拒绝归组 —— 越是随手命名的老师越用不了。
        # 用第一页的原始路径判断（多页时 source 是「a、b」拼起来的，不能直接拆目录）
        rel = next((p.get('source') for p in stu['pages'] if p.get('source')), '') or stu['fileSid']
        # 提示里要写**文件名**而不是解析出来的数字串：IMG_0001.png 的 fileSid 是 "0001"，
        # 把它当成「文件名里的考号」讲给老师听，比不说还让人糊涂。
        stu['fileName'] = os.path.basename(str(rel).replace('\\', '/').split('、')[0]) or stu['fileSid']
        strong = SID_RE.fullmatch(stu['fileSid']) and \
            file_sid_strong(rel, stu['fileSid'], roster)
        stu['fileSidStrong'] = bool(strong)
        stu['sidSource'] = 'file' if SID_RE.fullmatch(stu['fileSid']) else 'file-stem'

        if text and '?' in text:
            fixed, hits = resolve_sid(text, roster or {})
            stu['sidSuggest'] = hits
            if fixed:
                stu['sid'] = fixed
                stu['sidSource'] = 'roster'
                stu['note'] = (f'卷面考号 {text} 有 {text.count("?")} 位没涂出来，'
                               f'名单里只有 {fixed} 符合，已按这个考号归组')
            else:
                stu['sid'] = text
                stu['sidSource'] = 'sheet-partial'
                stu['baseIssues'] = list(stu.get('baseIssues') or []) + [
                    f'卷面考号有 {text.count("?")} 位没涂出来（{text}），'
                    + (f'名单里有 {len(hits)} 个人符合，请人工认领' if hits else '名单里也认不出来，请人工填写')]
            continue

        if strong:
            if text == stu['fileSid']:
                stu['sidSource'] = 'both'
            elif text:
                stu['sidSource'] = 'conflict'
                stu['baseIssues'] = list(stu.get('baseIssues') or []) + [
                    f'文件名里的考号（{stu["fileSid"]}，见 {stu["fileName"]}）和卷面涂的（{text}）'
                    f'不一致 —— 已按文件名归组，请人工确认这份卷子该记到谁名下']
            continue

        if text:
            stu['sid'] = text
            stu['sidSource'] = 'sheet'
            stu['note'] = f'文件名（{stu["fileName"]}）里没有考号，按卷面涂的 {text} 归组'
        elif len(stu['pages']) > 1:
            stu['baseIssues'] = list(stu.get('baseIssues') or []) + [
                f'文件名（{stu["fileName"]}）里的数字不太像考号，卷面也没读到考号 —— '
                f'{len(stu["pages"])} 页被归到同一个人，请确认']

    # 只有「身份是从卷面认出来的」才允许合并 —— 文件名已经写了考号的，身份本来就
    # 明确，万一卷面读串了，合并等于把两个人并成一个。
    out, bykey = [], {}
    for stu in students:
        key = str(stu['sid'])
        mergeable = stu['sidSource'] in ('sheet', 'roster') and '?' not in key
        if not mergeable or key not in bykey:
            if mergeable:
                bykey[key] = stu
            out.append(stu)
            continue
        tgt = bykey[key]
        before = len(tgt['pages'])
        _absorb(tgt, stu)
        tgt['note'] = (tgt.get('note') or '') + \
            f'（{stu["fileName"]} 也读到这个考号，已并为同一人的多页：{before} → {len(tgt["pages"])} 页）'
    return out


def suggest_sid(sid, roster, limit=4):
    """名单里与 sid 只差一位数字的考号。

    填涂错一位是这类卡子最常见的手误。但**调用方只在恰好命中一个时才给出建议** ——
    不少学校考号是连号的（…234/235/236），一个陌生的 237 会和好几个「只差一位」，
    那时候列出来只是噪音。所以这里返回全部候选，由 match() 决定要不要说。
    """
    sid = str(sid or '')
    if not roster or not sid or '?' in sid or sid in roster:
        return []                       # 本来就在名单里 → 没什么可建议的
    hits = []
    for k in roster:
        k = str(k)
        if len(k) != len(sid):
            continue
        if sum(1 for a, b in zip(k, sid) if a != b) == 1:
            hits.append(k)
            if len(hits) >= limit:
                break
    return hits


# 相机/扫描仪自动命名的文件里也有一串数字，但那是序号或时间戳，不是考号。
# 不把这类名字和「有人特意写的考号」区分开，就会出现最尴尬的情况：
#   IMG_0001.png 卷面上明明读到了 2026010234，却因为文件名里的 "0001" 被判成
#   「两个考号打架」，于是拒绝归组 —— 越不认识命名习惯的老师越用不了。
DEVICE_RE = re.compile(
    r'^(img|dsc|dscn|dji|gopr|imgp|scan\w*|scn|image|photo|pic|mvimg|vid|screenshot|'
    r'截屏|截图|扫描|扫描件|照片|图像|相机|图片|微信图片|微信截图)[-_\s]*\d', re.I)
STAMP_RE = re.compile(r'^\d{8}[-_\s]?\d{4,6}([-_\s]\d+)?$')     # 20240925_103012
SUFFIX_JUNK = re.compile(r'[\s_\-.,()（）\[\]【】]+')


def file_sid_strong(relpath, sid, roster=None):
    """文件名里那串数字，像不像「有人特意写的考号」？

    像（True）：写在目录名里（按考生分文件夹）、整段名字就是这个号码（可带 _1 页后缀）、
              「姓名-考号」这种写法、或者名单里真有这个考号。
    不像（False）：IMG_0001 / DSC_0123 / 扫描件_20240925_1030 —— 数字是序号或日期。
    不像的时候，如果卷面读到了考号，就该以卷面为准。
    """
    sid = str(sid)
    rel = str(relpath).replace('\\', '/')
    parts = [p for p in rel.split('/') if p]
    stem = os.path.splitext(parts[-1])[0] if parts else ''
    if roster and sid in roster:
        return True                                  # 名单里有这个人 → 显然是特意写的
    if any(sid in d for d in parts[:-1]):
        return True                                  # 目录里写了 → 特意按考生分的文件夹
    if DEVICE_RE.match(stem) or STAMP_RE.match(stem):
        return False
    if re.search(r'[\u4e00-\u9fff]', stem):
        return True                                  # 「张伟明-2026010234」
    rest = SUFFIX_JUNK.sub('', stem.replace(sid, '', 1))
    return rest == '' or rest.isdigit()              # 只剩页号（2026010234_1）也算
