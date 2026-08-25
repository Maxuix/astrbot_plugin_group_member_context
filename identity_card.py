"""HTML template for group identity member cards."""

IDENTITY_CARD_TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    :root { --paper: #efefe8; --panel: #f8f8f2; --alt: #e4e5df; --ink: #171818; --muted: #676a65; --yellow: #f3ed00; }
    * { box-sizing: border-box; }
    body { width: 760px; margin: 0; padding: 12px; background: var(--paper); color: var(--ink); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
    .member-card { padding: 24px; border: 2px solid var(--ink); background: var(--panel); box-shadow: 5px 5px 0 var(--ink); }
    .member-head { display: flex; align-items: center; gap: 24px; margin-bottom: 20px; }
    .avatar { display: grid; place-items: center; flex: 0 0 72px; width: 72px; height: 72px; overflow: hidden; border: 2px solid var(--ink); background: var(--yellow); font-size: 25px; font-weight: 900; }
    .avatar img { width: 100%; height: 100%; object-fit: cover; }
    .member-name { margin: 0 0 5px; font-size: 27px; line-height: 1.15; overflow-wrap: anywhere; }
    .member-meta { margin: 0; color: var(--muted); font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .05em; }
    .identity-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
    .identity-title { display: grid; place-items: center; flex: 0 0 88px; height: 28px; border: 1px solid var(--ink); background: var(--yellow); font-size: 13px; font-weight: 700; }
    .identity-line { flex: 1; height: 2px; background: var(--ink); }
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
    <div class="identity-head">
      <div class="identity-title">身份信息</div>
      <div class="identity-line"></div>
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
