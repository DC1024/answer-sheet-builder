// 设置 / 检查更新
//
// 制卡端没有后端，所以：
//   * 偏好（要不要自动查更新）存 localStorage；
//   * 更新检查直接问 GitHub 的公开 API（它带 CORS 头，浏览器能直接跨域 GET）。
// 内网/离线时查询会失败 —— 那只是「暂时查不到」，不是错误，不弹红。
import { APP_VERSION, LATEST_API, RELEASES_URL } from './version.js';

const LS_KEY = 'asb.settings';
export const CHECK_INTERVAL = 6 * 3600 * 1000;   // 自动检查最短间隔：6 小时

const DEFAULTS = { autoCheckUpdate: true, lastCheck: 0, lastResult: null };

export function loadSettings(){
  try {
    const raw = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    return Object.assign({}, DEFAULTS, raw && typeof raw === 'object' ? raw : {});
  } catch (e){
    return Object.assign({}, DEFAULTS);
  }
}

export function saveSettings(patch){
  const next = Object.assign(loadSettings(), patch || {});
  try { localStorage.setItem(LS_KEY, JSON.stringify(next)); } catch (e){ /* 隐私模式等，忽略 */ }
  return next;
}

/* ---------- 版本号比较 ---------- */
// `v1.0.3` / `1.0.3` / `1.0.3-rc.1` → [1, 0, 3]；不追求完全符合 semver，
// 只要能可靠回答「新的比旧的大吗」。
export function parseVersion(text){
  const s = String(text == null ? '' : text).trim().replace(/^[vV]/, '').split('+')[0];
  const core = s.split(/[-_]/)[0];
  const parts = core.split('.').map(p => {
    const m = /^\d+/.exec(p);
    return m ? parseInt(m[0], 10) : 0;
  });
  while (parts.length < 3) parts.push(0);
  return parts.slice(0, 3);
}

export function isNewer(latest, current){
  try {
    const a = parseVersion(latest), b = parseVersion(current);
    for (let i = 0; i < 3; i++){
      if (a[i] !== b[i]) return a[i] > b[i];
    }
    return false;
  } catch (e){ return false; }
}

/* ---------- 查更新 ---------- */
// 永远 resolve，失败信息放在 error 里（和扫描端的 app/update.py 保持同一套语义）。
export async function checkUpdate(current = APP_VERSION){
  const out = { ok: false, current, latest: '', hasUpdate: false, url: RELEASES_URL,
                name: '', notes: '', publishedAt: '', error: '' };
  let r;
  try {
    r = await fetch(LATEST_API, { headers: { Accept: 'application/vnd.github+json' }, cache: 'no-store' });
  } catch (e){
    out.error = '连不上 GitHub —— 内网/离线环境属正常，可手动访问发行版页面';
    return out;
  }
  if (!r.ok){
    if (r.status === 404) out.error = '这个仓库还没有发布过 Release';
    else if (r.status === 403 || r.status === 429) out.error = 'GitHub 暂时限制了查询频率，稍后再试';
    else out.error = 'GitHub 返回 HTTP ' + r.status;
    return out;
  }
  let d;
  try { d = await r.json(); } catch (e){ out.error = 'GitHub 返回的内容看不懂'; return out; }
  const tag = String(d.tag_name || '').trim();
  return {
    ok: true, current,
    latest: tag,
    hasUpdate: isNewer(tag, current),
    url: d.html_url || RELEASES_URL,
    name: String(d.name || tag).trim(),
    notes: String(d.body || '').trim(),
    publishedAt: String(d.published_at || ''),
    error: '',
  };
}

// 打开页面时自动查一次；6 小时内直接用上次结果，不重复打 GitHub。
export function maybeAutoCheck(onResult){
  const s = loadSettings();
  if (!s.autoCheckUpdate) return;
  if (s.lastResult && s.lastResult.ok && (Date.now() - (s.lastCheck || 0)) < CHECK_INTERVAL){
    if (onResult) onResult(s.lastResult, true);
    return;
  }
  checkUpdate().then(res => {
    if (res.ok) saveSettings({ lastCheck: Date.now(), lastResult: res });
    if (onResult) onResult(res, false);
  });
}

/* ---------- 设置弹窗 ---------- */
const $ = id => document.getElementById(id);

let picked = null;          // 最后一次「有新版本」的结果，页头横幅用得上

export function hasPendingUpdate(){ return !!picked; }

function fmtTime(iso){
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleString();
}

function renderResult(res, cached){
  const box = $('setResult'), info = $('setInfo');
  if (!res){
    box.hidden = true;
    return;
  }
  if (!res.ok){
    // 「查不到」不是错误：给出人话原因 + 手动入口，不弹红
    info.textContent = '';
    box.hidden = false;
    box.className = '';
    box.innerHTML = `<b>暂时查不到新版本</b><br>${escapeHtml(res.error || '未知原因')}
      <br><span class="hint">可以直接访问
      <a href="${RELEASES_URL}" target="_blank" rel="noreferrer">项目发行版页面</a> 看看。</span>`;
    return;
  }
  if (res.hasUpdate){
    picked = res;
    info.textContent = '';
    box.hidden = false;
    box.className = 'hit';
    box.innerHTML = `🎉 发现新版本 <b>${escapeHtml(res.latest)}</b>，当前是 <b>v${escapeHtml(res.current)}</b>
      ${res.publishedAt ? `<span class="hint">· ${escapeHtml(fmtTime(res.publishedAt))}</span>` : ''}。
      <a href="${escapeAttr(res.url)}" target="_blank" rel="noreferrer">打开发行版页面 →</a>`
      + (res.notes ? `<pre>${escapeHtml(res.notes)}</pre>` : '');
  } else {
    picked = null;
    info.textContent = `已是最新版本（v${res.current}${cached ? ' · 用缓存' : ''}）`;
    box.hidden = true;
  }
}

function escapeHtml(s){
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
const escapeAttr = escapeHtml;

export function openSettings(){
  const modal = $('setModal');
  if (!modal) return;
  const s = loadSettings();
  $('setVer').textContent = 'v' + APP_VERSION;
  $('setAutoUpd').checked = !!s.autoCheckUpdate;
  $('setReleases').href = RELEASES_URL;
  renderResult(s.lastResult && s.lastResult.ok ? s.lastResult : null, true);
  modal.hidden = false;
}

export function closeSettings(){
  const modal = $('setModal');
  if (modal) modal.hidden = true;
}

export function bindSettings(){
  const modal = $('setModal');
  if (!modal) return;

  $('btn-settings').addEventListener('click', openSettings);
  $('setClose').addEventListener('click', closeSettings);
  modal.addEventListener('click', e => { if (e.target === modal) closeSettings(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !modal.hidden) closeSettings();
  });

  $('setAutoUpd').addEventListener('change', e => {
    saveSettings({ autoCheckUpdate: !!e.target.checked });
    if (e.target.checked) doCheck(false);
  });

  $('setCheck').addEventListener('click', () => doCheck(true));
  $('setReleases').addEventListener('click', e => { e.preventDefault(); window.open(RELEASES_URL, '_blank', 'noopener'); });

  maybeAutoCheck((res, cached) => {
    // 后台自动查的结果只用来「亮一个角标」，不打断用户
    if (res && res.ok && res.hasUpdate){
      picked = res;
      const btn = $('btn-settings');
      if (btn && !btn.dataset.badge){
        btn.dataset.badge = '1';
        btn.textContent = '⚙ 设置 ●';
        btn.title = `有新版本 ${res.latest}，点击查看`;
        btn.classList.add('hasUpdate');
      }
    }
  });
}

async function doCheck(force){
  const btn = $('setCheck'), info = $('setInfo'), box = $('setResult');
  btn.disabled = true; info.textContent = '正在查询…'; box.hidden = true;
  const res = await checkUpdate();
  if (res.ok) saveSettings({ lastCheck: Date.now(), lastResult: res });
  renderResult(res, false);
  btn.disabled = false;
  if (force && res.ok && !res.hasUpdate) info.textContent = `已是最新版本（v${res.current}）`;
}
