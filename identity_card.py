"""HTML template for the group member identity list card."""

IDENTITY_CARD_TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    :root {
      --paper: #efefe8;
      --panel: #f7f7f1;
      --panel-alt: #e4e5df;
      --ink: #141515;
      --muted: #666963;
      --line: #292b29;
      --yellow: #f3ed00;
      --green: #15966a;
      --red: #bd354b;
    }
    * { box-sizing: border-box; }
    body {
      width: 820px;
      margin: 0;
      padding: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
    }
    .frame { border-left: 7px solid var(--yellow); }
    .masthead {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 92px;
      padding: 18px 28px;
      border-bottom: 4px solid var(--yellow);
      background: #141515;
      color: #f3f4ec;
    }
    .kicker, .status, .section-label, .field-label, .footer {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-weight: 700;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .kicker { margin: 0 0 5px; color: var(--yellow); font-size: 11px; }
    .title { margin: 0; font-size: 20px; letter-spacing: .06em; }
    .status { display: flex; align-items: center; gap: 9px; color: #c8ccc1; font-size: 10px; }
    .status-dot { width: 9px; height: 9px; background: {{ '#15966a' if injection_enabled else '#bd354b' }}; }
    .content { padding: 30px 32px 26px; }
    .hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
    .hero h1 { margin: 0 0 8px; font-size: 43px; line-height: 1; letter-spacing: -.055em; }
    .hero p { margin: 0; color: var(--muted); }
    .index {
      display: grid;
      place-items: center;
      width: 62px;
      height: 62px;
      border: 2px solid var(--line);
      background: var(--yellow);
      font: 900 22px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
      box-shadow: 4px 4px 0 var(--line);
    }
    .rule { height: 2px; margin: 24px 0; background: var(--line); }
    .member-card {
      padding: 24px;
      border: 2px solid var(--line);
      background: var(--panel);
      box-shadow: 5px 5px 0 var(--line);
    }
    .member-head { display: flex; align-items: center; gap: 18px; margin-bottom: 22px; }
    .avatar {
      display: grid;
      place-items: center;
      flex: 0 0 68px;
      width: 68px;
      height: 68px;
      border: 2px solid var(--line);
      background: var(--yellow);
      font-size: 25px;
      font-weight: 900;
    }
    .member-name { margin: 0 0 4px; font-size: 26px; line-height: 1.15; }
    .member-meta { margin: 0; color: var(--muted); font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .identity-grid { display: grid; grid-template-columns: 150px 1fr; border-top: 2px solid var(--line); }
    .field-label, .field-values { padding: 13px 14px; border-bottom: 1px solid #b8bbb3; }
    .field-label { background: var(--panel-alt); font-size: 11px; }
    .field-values { border-left: 1px solid #b8bbb3; font-weight: 650; overflow-wrap: anywhere; }
    .empty {
      padding: 22px;
      border: 2px dashed #8a8e86;
      color: var(--muted);
      text-align: center;
    }
    .footer { display: flex; justify-content: space-between; margin-top: 20px; color: var(--muted); font-size: 10px; }
  </style>
</head>
<body>
  <div class="frame">
    <header class="masthead">
      <div>
        <p class="kicker">ASTRBOT / GROUP MEMBER CONTEXT</p>
        <p class="title">IDENTITY REFERENCE CARD</p>
      </div>
      <div class="status">
        <span class="status-dot"></span>
        <span>INJECTION</span>
        <strong>{{ 'ON' if injection_enabled else 'OFF' }}</strong>
      </div>
    </header>
    <main class="content">
      <section class="hero">
        <div>
          <p class="section-label">MEMBER IDENTITY / {{ group_id | e }}</p>
          <h1>{{ group_name | e }}</h1>
          <p>当前群成员身份资料</p>
        </div>
        <div class="index">ID</div>
      </section>
      <div class="rule"></div>
      <section class="member-card">
        <div class="member-head">
          <div class="avatar">{{ avatar_text | e }}</div>
          <div>
            <h2 class="member-name">{{ display_name | e }}</h2>
            <p class="member-meta">QQ {{ user_id | e }}{% if card %} / 群名片 {{ card | e }}{% endif %}</p>
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
        <div class="empty">该成员尚未配置可公开查看的身份。</div>
        {% endif %}
      </section>
      <footer class="footer">
        <span>GROUP MEMBER CONTEXT / LOCAL DATA</span>
        <span>{{ field_count }} IDENTITY FIELDS</span>
      </footer>
    </main>
  </div>
</body>
</html>
"""
