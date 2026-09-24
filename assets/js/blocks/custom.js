// 模块：自定义编辑区（可自由填写文字内容，含可选标题）
import { esc, commonStyle } from '../core/util.js';

export default {
  type: 'custom',
  name: '自定义编辑区',
  icon: '📝',
  defaults: () => ({ title: '', content: '在此输入自定义内容，例如：注意事项、草稿区、图文说明等。' }),

  configUI(container, config, onChange){
    container.innerHTML = `
      <label>标题（留空则不显示）
        <input type="text" data-k="title" value="${esc(config.title)}" placeholder="例如：注意事项">
      </label>
      <label>内容（支持换行）
        <textarea data-k="content">${esc(config.content)}</textarea>
      </label>
      <p class="hint">内容按纯文本渲染，换行会被保留。</p>
    `;
    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="content"]').addEventListener('input', e => { config.content = e.target.value; onChange(); });
  },

  render(config){
    const title = config.title ? `<div class="ch">${esc(config.title)}</div>` : '';
    return `<div class="blk" style="${commonStyle(config)}"><div class="custom-box">${title}<div class="cb">${esc(config.content)}</div></div></div>`;
  }
};
