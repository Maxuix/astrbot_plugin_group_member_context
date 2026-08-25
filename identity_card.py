"""HTML templates for group identity command images."""

IDENTITY_CARD_TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    :root { --paper: #efefe8; --panel: #f8f8f2; --alt: #e4e5df; --ink: #171818; --muted: #676a65; --yellow: #f3ed00; }
    * { box-sizing: border-box; }
    body { width: 760px; margin: 0; padding: 30px; background: var(--paper); color: var(--ink); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
    .member-card { padding: 28px; border: 2px solid var(--ink); background: var(--panel); box-shadow: 6px 6px 0 var(--ink); }
    .member-head { display: flex; align-items: center; gap: 20px; margin-bottom: 24px; }
    .avatar { display: grid; place-items: center; flex: 0 0 78px; width: 78px; height: 78px; overflow: hidden; border: 2px solid var(--ink); background: var(--yellow); font-size: 25px; font-weight: 900; }
    .avatar img { width: 100%; height: 100%; object-fit: cover; }
    .member-name { margin: 0 0 5px; font-size: 28px; line-height: 1.15; overflow-wrap: anywhere; }
    .member-meta { margin: 0; color: var(--muted); font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .05em; }
    .identity-grid { display: grid; grid-template-columns: 150px 1fr; border-top: 2px solid var(--ink); }
    .field-label, .field-values { padding: 13px 15px; border-bottom: 1px solid #b8bbb3; }
    .field-label { background: var(--alt); font: 700 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .field-values { border-left: 1px solid #b8bbb3; font-weight: 650; overflow-wrap: anywhere; }
    .empty { padding: 22px; border-top: 2px solid var(--ink); color: var(--muted); text-align: center; }
  </style>
</head>
<body>
  <section class="member-card">
    <div class="member-head">
      <div class="avatar">
        {% if avatar_data_url %}<img src="{{ avatar_data_url | e }}" alt="" />{% else %}{{ avatar_text | e }}{% endif %}
      </div>
      <div>
        <h1 class="member-name">{{ display_name | e }}</h1>
        <p class="member-meta">QQ {{ user_id | e }}</p>
      </div>
    </div>
    {% if fields %}
    <div class="identity-grid">
      {% for field in fields %}
      <div class="field-label">{{ field["label"] | e }}</div>
      <div class="field-values">{{ field["values"] | join(' · ') | e }}</div>
      {% endfor %}
    </div>
    {% else %}
    <div class="empty">该成员尚未配置身份。</div>
    {% endif %}
  </section>
</body>
</html>
"""


HELP_CARD_TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    :root { --paper: #efefe8; --panel: #f8f8f2; --alt: #e4e5df; --ink: #171818; --muted: #676a65; --yellow: #f3ed00; }
    * { box-sizing: border-box; }
    body { width: 900px; margin: 0; padding: 30px; background: var(--paper); color: var(--ink); font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
    .card { padding: 30px; border: 2px solid var(--ink); background: var(--panel); box-shadow: 6px 6px 0 var(--ink); }
    .head { display: flex; align-items: center; gap: 20px; margin-bottom: 25px; }
    .mark { display: grid; place-items: center; flex: 0 0 78px; width: 78px; height: 78px; border: 2px solid var(--ink); background: var(--yellow); font: 900 34px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    h1 { margin: 0 0 4px; font-size: 30px; line-height: 1.15; }
    .subtitle { margin: 0; color: var(--muted); }
    .section { display: grid; grid-template-columns: 150px 1fr; border-top: 2px solid var(--ink); }
    .label { padding: 15px; background: var(--alt); border-bottom: 1px solid #b8bbb3; font: 700 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .content { padding: 13px 17px; border-left: 1px solid #b8bbb3; border-bottom: 1px solid #b8bbb3; }
    .command { display: block; margin: 2px 0; font: 650 14px/1.65 ui-monospace, SFMono-Regular, Menlo, "PingFang SC", monospace; overflow-wrap: anywhere; }
    .note { margin: 2px 0; color: #363936; }
  </style>
</head>
<body>
  <section class="card">
    <header class="head">
      <div class="mark">?</div>
      <div>
        <h1>群身份指令帮助</h1>
        <p class="subtitle">身份内容未指定标签时，默认使用“昵称”。</p>
      </div>
    </header>
    <div class="section">
      <div class="label">身份格式</div>
      <div class="content">
        <span class="command">&lt;身份&gt;</span>
        <span class="command">&lt;身份标签&gt;=&lt;身份&gt;</span>
      </div>
      <div class="label">普通成员命令</div>
      <div class="content">
        <span class="command">/群身份 me &lt;身份表达式&gt;</span>
        <span class="command">/群身份 merm &lt;身份表达式&gt;</span>
        <span class="command">/群身份 list [@群成员/QQ号]</span>
        <span class="command">/群身份 help</span>
      </div>
      <div class="label">管理员命令</div>
      <div class="content">
        <span class="command">/群身份 add &lt;@群成员/QQ号&gt; &lt;身份表达式&gt;</span>
        <span class="command">/群身份 remove &lt;@群成员/QQ号&gt; &lt;身份表达式&gt;</span>
        <span class="command">/群身份 tag add &lt;身份标签&gt;</span>
        <span class="command">/群身份 tag remove &lt;身份标签&gt;</span>
        <span class="command">/群身份 on</span>
        <span class="command">/群身份 off</span>
      </div>
      <div class="label">使用示例</div>
      <div class="content">
        <span class="command">/群身份 me Tony</span>
        <span class="command">/群身份 add @小明 游戏名=Tony Stark</span>
        <span class="command">/群身份 remove 123456789 游戏名=Tony Stark</span>
        <span class="command">/群身份 tag add 游戏名</span>
      </div>
      <div class="label">说明</div>
      <div class="content">
        <p class="note">me 与 merm 使用自定义标签时仅限管理员，且标签须先通过 tag add 创建。</p>
        <p class="note">tag remove 不会删除身份数据；标签仍被成员使用时会拒绝删除。</p>
        <p class="note">管理员权限按群设置，白名单非空时优先于黑名单。</p>
      </div>
    </div>
  </section>
</body>
</html>
"""
