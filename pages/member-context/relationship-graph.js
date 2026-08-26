const BOT_NODE_ID = "__self__";
const MAX_MEMBER_NODES = 80;
const MAX_EDGES = 200;
const MAX_CUSTOM_TYPES = 16;
const MIN_SCALE = 0.45;
const MAX_SCALE = 2.2;
const NODE_RADIUS = 28;
const CUSTOM_COLORS = [
  "#e85d4c",
  "#3d8bfd",
  "#12b886",
  "#cc5de8",
  "#f08c00",
  "#22b8cf",
  "#fa5252",
  "#5c7cfa",
  "#82c91e",
  "#e64980",
  "#15aabf",
  "#fd7e14",
  "#7950f2",
  "#12a37a",
  "#d9480f",
  "#4263eb",
  "#2f9e44",
  "#c2255c",
  "#0ca678",
  "#e67700",
];

export function emptyRelationshipGraph() {
  return {
    relationship_injection_enabled: false,
    relationship_types: [],
    relationship_nodes: [],
    relationship_edges: [],
  };
}

export function createRelationshipGraph(options) {
  const root = options.root;
  const onChange = options.onChange || (() => {});
  const onNotice = options.onNotice || (() => {});
  const getMembers = options.getMembers || (() => []);
  const getBot = options.getBot || (() => ({ user_id: "", nickname: "" }));
  const getAvatarRevision = options.getAvatarRevision || (() => "");

  const refs = {
    enabled: root.querySelector("#relationship-enabled"),
    status: root.querySelector("#graph-status"),
    librarySearch: root.querySelector("#graph-library-search"),
    libraryList: root.querySelector("#graph-library-list"),
    types: root.querySelector("#graph-type-list"),
    viewport: root.querySelector("#graph-viewport"),
    world: root.querySelector("#graph-world"),
    edges: root.querySelector("#graph-edges"),
    nodes: root.querySelector("#graph-nodes"),
    empty: root.querySelector("#graph-empty"),
    peerPreview: root.querySelector("#peer-relationship-preview"),
    botPreview: root.querySelector("#bot-relationship-preview"),
    customName: root.querySelector("#graph-custom-name"),
    customDirected: root.querySelector("#graph-custom-directed"),
    customAdd: root.querySelector("#graph-custom-add"),
    hint: root.querySelector("#graph-hint"),
    menu: root.querySelector("#graph-menu"),
    clearDialog: root.querySelector("#graph-clear-dialog"),
    clearCancel: root.querySelector("#graph-clear-cancel"),
    clearConfirm: root.querySelector("#graph-clear-confirm"),
  };

  const view = { x: 360, y: 260, scale: 1 };
  const graph = emptyRelationshipGraph();
  const interaction = {
    typeId: "",
    selected: null,
    space: false,
    panning: null,
    dragging: null,
    connecting: null,
    clickConnectFrom: null,
    dropTarget: null,
    menuOpenedAt: 0,
  };

  function emitChange() {
    onChange(getGraph());
    renderStatus();
    renderPreview();
  }

  function getGraph() {
    return {
      relationship_injection_enabled: graph.relationship_injection_enabled,
      relationship_types: graph.relationship_types.map((item) => ({ ...item })),
      relationship_nodes: graph.relationship_nodes.map((item) => ({ ...item })),
      relationship_edges: graph.relationship_edges.map((item) => ({ ...item })),
    };
  }

  function setGraph(next) {
    const source = next && typeof next === "object" ? next : {};
    graph.relationship_injection_enabled = source.relationship_injection_enabled === true;
    graph.relationship_types = Array.isArray(source.relationship_types)
      ? source.relationship_types
          .map((item) => ({ ...item }))
          .filter((item) => item.id !== "owner" && item.label !== "主人")
      : [];
    graph.relationship_nodes = Array.isArray(source.relationship_nodes)
      ? source.relationship_nodes.map((item) => ({ ...item }))
      : [];
    const allowedTypes = new Set(graph.relationship_types.map((item) => item.id));
    graph.relationship_edges = Array.isArray(source.relationship_edges)
      ? source.relationship_edges
          .map((item) => ({ ...item }))
          .filter((item) => item.type_id !== "owner" && allowedTypes.has(item.type_id))
      : [];
    if (refs.enabled) refs.enabled.checked = graph.relationship_injection_enabled;
    interaction.selected = null;
    if (!graph.relationship_types.some((item) => item.id === interaction.typeId)) {
      interaction.typeId = "";
    }
    hideMenu();
    renderAll();
  }

  function typesById() {
    return new Map(graph.relationship_types.map((item) => [item.id, item]));
  }

  function nodeById(id) {
    return graph.relationship_nodes.find((node) => node.id === id);
  }

  function memberMap() {
    const map = new Map();
    for (const member of getMembers()) map.set(String(member.user_id), member);
    return map;
  }

  function displayName(userId) {
    const member = memberMap().get(String(userId));
    if (!member) return String(userId);
    return String(member.card || member.nickname || member.user_id);
  }

  function allocateId(prefix, used) {
    let index = 1;
    let candidate = `${prefix}${index}`;
    while (used.has(candidate)) {
      index += 1;
      candidate = `${prefix}${index}`;
    }
    return candidate;
  }

  function nextCustomColor() {
    const used = new Set(graph.relationship_types.map((item) => String(item.color || "").toLowerCase()));
    return CUSTOM_COLORS.find((color) => !used.has(color)) || CUSTOM_COLORS[graph.relationship_types.length % CUSTOM_COLORS.length];
  }

  function screenToWorld(clientX, clientY) {
    const rect = refs.viewport.getBoundingClientRect();
    return {
      x: (clientX - rect.left - view.x) / view.scale,
      y: (clientY - rect.top - view.y) / view.scale,
    };
  }

  function applyView() {
    refs.world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  }

  function nextFreePoint() {
    const taken = new Set(
      graph.relationship_nodes.map((node) => `${Math.round(node.x / 96)},${Math.round(node.y / 96)}`),
    );
    for (let index = 0; index < 96; index += 1) {
      const col = index % 8;
      const row = Math.floor(index / 8);
      const x = (col - 3) * 96;
      const y = (row - 1) * 96;
      if (!taken.has(`${Math.round(x / 96)},${Math.round(y / 96)}`)) return { x, y };
    }
    return { x: Math.random() * 80, y: Math.random() * 80 };
  }

  function addMemberNode(userId, point) {
    const id = String(userId);
    if (nodeById(id)) {
      onNotice("该成员已在关系网中。", "warning");
      return null;
    }
    const memberCount = graph.relationship_nodes.filter((node) => node.kind !== "bot").length;
    if (memberCount >= MAX_MEMBER_NODES) {
      onNotice(`画布最多 ${MAX_MEMBER_NODES} 名群成员。`, "warning");
      return null;
    }
    const position = point || nextFreePoint();
    graph.relationship_nodes.push({
      id,
      kind: "member",
      user_id: id,
      x: position.x,
      y: position.y,
    });
    renderNodes();
    renderLibrary();
    renderEdges();
    emitChange();
    return nodeById(id);
  }

  function addBotNode(point) {
    if (nodeById(BOT_NODE_ID)) {
      onNotice("本机器人已在关系网中。", "warning");
      return null;
    }
    const position = point || nextFreePoint();
    graph.relationship_nodes.push({ id: BOT_NODE_ID, kind: "bot", x: position.x, y: position.y });
    renderNodes();
    renderLibrary();
    renderEdges();
    emitChange();
    return nodeById(BOT_NODE_ID);
  }

  function pairKey(source, target) {
    return [source, target].sort().join("~");
  }

  function edgeDedupeKey(source, target, typeId, directed) {
    return directed ? `${source}>${target}:${typeId}` : `${pairKey(source, target)}:${typeId}`;
  }

  function addEdge(source, target, typeId) {
    if (!source || !target || source === target) return;
    const type = typesById().get(typeId);
    if (!type) {
      onNotice("请先选择一种关系线。", "warning");
      return;
    }
    if (graph.relationship_edges.length >= MAX_EDGES) {
      onNotice(`最多 ${MAX_EDGES} 条关系。`, "warning");
      return;
    }
    const directed = type.directed === true;
    const key = edgeDedupeKey(source, target, typeId, directed);
    const exists = graph.relationship_edges.some((edge) => {
      const item = typesById().get(edge.type_id);
      return edgeDedupeKey(edge.source, edge.target, edge.type_id, item?.directed === true) === key;
    });
    if (exists) {
      onNotice("这条关系已经存在。", "warning");
      return;
    }
    const used = new Set(graph.relationship_edges.map((edge) => edge.id));
    graph.relationship_edges.push({
      id: allocateId("e_", used),
      source,
      target,
      type_id: typeId,
    });
    renderEdges();
    emitChange();
  }

  function removeSelection() {
    const selected = interaction.selected;
    if (!selected) return;
    if (selected.kind === "node") {
      graph.relationship_nodes = graph.relationship_nodes.filter((node) => node.id !== selected.id);
      graph.relationship_edges = graph.relationship_edges.filter(
        (edge) => edge.source !== selected.id && edge.target !== selected.id,
      );
    } else if (selected.kind === "edge") {
      graph.relationship_edges = graph.relationship_edges.filter((edge) => edge.id !== selected.id);
    }
    interaction.selected = null;
    hideMenu();
    renderAll();
    emitChange();
  }

  function reverseSelectedEdge() {
    const selected = interaction.selected;
    const edge = selected?.kind === "edge"
      ? graph.relationship_edges.find((item) => item.id === selected.id)
      : null;
    const type = edge ? typesById().get(edge.type_id) : null;
    if (!edge || type?.directed !== true) {
      onNotice("只有有向关系可以对调方向。", "warning");
      return;
    }
    const nextSource = edge.target;
    const nextTarget = edge.source;
    const key = edgeDedupeKey(nextSource, nextTarget, edge.type_id, true);
    const clash = graph.relationship_edges.some(
      (item) => item.id !== edge.id && edgeDedupeKey(item.source, item.target, item.type_id, true) === key,
    );
    if (clash) {
      onNotice("反向关系已经存在。", "warning");
      return;
    }
    edge.source = nextSource;
    edge.target = nextTarget;
    hideMenu();
    renderEdges();
    emitChange();
  }

  function clearGraph() {
    graph.relationship_nodes = [];
    graph.relationship_edges = [];
    interaction.selected = null;
    hideMenu();
    renderAll();
    emitChange();
  }

  function cleanupLeftMembers() {
    const known = new Set(getMembers().map((member) => String(member.user_id)));
    const removed = new Set(
      graph.relationship_nodes
        .filter((node) => node.kind === "member" && !known.has(node.id))
        .map((node) => node.id),
    );
    if (!removed.size) {
      onNotice("没有已退群节点。", "info");
      return;
    }
    graph.relationship_nodes = graph.relationship_nodes.filter((node) => !removed.has(node.id));
    graph.relationship_edges = graph.relationship_edges.filter(
      (edge) => !removed.has(edge.source) && !removed.has(edge.target),
    );
    renderAll();
    emitChange();
    onNotice(`已清理 ${removed.size} 个已退群节点。`, "success");
  }

  function undirectedPairs() {
    const seen = new Set();
    const pairs = [];
    for (const edge of graph.relationship_edges) {
      const key = pairKey(edge.source, edge.target);
      if (seen.has(key)) continue;
      seen.add(key);
      pairs.push([edge.source, edge.target]);
    }
    return pairs;
  }

  function crossingCount(order, pairs) {
    const index = new Map(order.map((id, i) => [id, i]));
    let count = 0;
    for (let i = 0; i < pairs.length; i += 1) {
      const a = index.get(pairs[i][0]);
      const b = index.get(pairs[i][1]);
      if (a == null || b == null) continue;
      const left = Math.min(a, b);
      const right = Math.max(a, b);
      for (let j = i + 1; j < pairs.length; j += 1) {
        const c = index.get(pairs[j][0]);
        const d = index.get(pairs[j][1]);
        if (c == null || d == null) continue;
        const lo = Math.min(c, d);
        const hi = Math.max(c, d);
        if ((left < lo && lo < right && right < hi) || (lo < left && left < hi && hi < right)) count += 1;
      }
    }
    return count;
  }

  function layoutGraph() {
    const nodes = graph.relationship_nodes;
    if (!nodes.length) return;
    const pairs = undirectedPairs();
    let order = nodes.map((node) => node.id);
    const botIndex = order.indexOf(BOT_NODE_ID);
    if (botIndex > 0) {
      order.splice(botIndex, 1);
      order.unshift(BOT_NODE_ID);
    }
    let best = crossingCount(order, pairs);
    let improved = true;
    for (let round = 0; round < 48 && improved; round += 1) {
      improved = false;
      for (let i = 0; i < order.length - 1; i += 1) {
        for (let j = i + 2; j < order.length; j += 1) {
          const next = order.slice(0, i).concat(order.slice(i, j + 1).reverse(), order.slice(j + 1));
          const score = crossingCount(next, pairs);
          if (score < best) {
            order = next;
            best = score;
            improved = true;
          }
        }
      }
    }
    const radius = Math.max(170, Math.round((order.length * 56) / Math.PI + 90));
    order.forEach((id, index) => {
      const node = nodeById(id);
      if (!node) return;
      const angle = (Math.PI * 2 * index) / order.length - Math.PI / 2;
      node.x = Math.round(Math.cos(angle) * radius);
      node.y = Math.round(Math.sin(angle) * radius);
    });
    renderNodes();
    renderEdges();
    fitView();
    emitChange();
  }

  function fitView() {
    const items = graph.relationship_nodes.map((node) => ({ x: node.x, y: node.y }));
    const rect = refs.viewport.getBoundingClientRect();
    if (!items.length || rect.width < 40 || rect.height < 40) {
      view.scale = 1;
      view.x = Math.max(rect.width, 200) / 2;
      view.y = Math.max(rect.height, 200) / 2;
      applyView();
      return;
    }
    const minX = Math.min(...items.map((item) => item.x)) - 90;
    const maxX = Math.max(...items.map((item) => item.x)) + 90;
    const minY = Math.min(...items.map((item) => item.y)) - 90;
    const maxY = Math.max(...items.map((item) => item.y)) + 90;
    const scale = Math.max(
      MIN_SCALE,
      Math.min(MAX_SCALE, Math.min(rect.width / Math.max(maxX - minX, 1), rect.height / Math.max(maxY - minY, 1))),
    );
    view.scale = scale;
    view.x = rect.width / 2 - ((minX + maxX) / 2) * scale;
    view.y = rect.height / 2 - ((minY + maxY) / 2) * scale;
    applyView();
  }

  function selectItem(selected) {
    interaction.selected = selected;
    renderNodes();
    renderEdges();
  }

  function hideMenu() {
    if (!refs.menu) return;
    refs.menu.classList.add("hidden");
    refs.menu.replaceChildren();
  }

  function openClearDialog() {
    if (!graph.relationship_nodes.length && !graph.relationship_edges.length) {
      onNotice("关系网已经是空的。", "info");
      return;
    }
    refs.clearDialog?.classList.remove("hidden");
  }

  function closeClearDialog() {
    refs.clearDialog?.classList.add("hidden");
  }

  function showMenu(clientX, clientY, items) {
    if (!refs.menu || !items.length) return;
    interaction.menuOpenedAt = Date.now();
    refs.menu.replaceChildren();
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "graph-menu-item";
      if (item.danger) button.classList.add("is-danger");
      button.textContent = item.label;
      const run = () => {
        hideMenu();
        item.run();
      };
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        run();
      });
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        run();
      });
      refs.menu.appendChild(button);
    }
    refs.menu.classList.remove("hidden");
    const rect = refs.viewport.getBoundingClientRect();
    refs.menu.style.left = `${Math.min(Math.max(8, clientX - rect.left), Math.max(8, rect.width - 168))}px`;
    refs.menu.style.top = `${Math.min(Math.max(8, clientY - rect.top), Math.max(8, rect.height - 8 - items.length * 34))}px`;
  }

  function renderLibrary() {
    const bot = getBot();
    const search = String(refs.librarySearch?.value || "").trim().toLowerCase();
    const onCanvas = new Set(graph.relationship_nodes.map((node) => node.id));
    refs.libraryList.replaceChildren();

    const botButton = document.createElement("button");
    botButton.type = "button";
    botButton.className = "graph-chip graph-chip-bot";
    botButton.draggable = !onCanvas.has(BOT_NODE_ID);
    botButton.disabled = onCanvas.has(BOT_NODE_ID);
    botButton.innerHTML = `<span class="graph-chip-badge">BOT</span><strong>本机器人</strong><small>${bot.nickname || "当前登录号"}</small><small>QQ：${bot.user_id || "未读取"}</small>`;
    botButton.addEventListener("click", () => addBotNode());
    botButton.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", "bot");
      event.dataTransfer.effectAllowed = "copy";
    });
    refs.libraryList.appendChild(botButton);

    for (const member of getMembers()) {
      const haystack = `${member.nickname || ""} ${member.card || ""} ${member.user_id || ""}`.toLowerCase();
      if (search && !haystack.includes(search)) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "graph-chip";
      button.draggable = !onCanvas.has(String(member.user_id));
      button.disabled = onCanvas.has(String(member.user_id));
      button.dataset.userId = String(member.user_id);
      const title = document.createElement("strong");
      title.textContent = member.nickname || "未设置昵称";
      const card = document.createElement("small");
      card.textContent = member.card ? `群备注：${member.card}` : "群备注：无";
      const qq = document.createElement("small");
      qq.textContent = `QQ：${member.user_id}`;
      button.append(title, card, qq);
      button.addEventListener("click", () => addMemberNode(member.user_id));
      button.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", `member:${member.user_id}`);
        event.dataTransfer.effectAllowed = "copy";
      });
      refs.libraryList.appendChild(button);
    }
  }

  function renderTypes() {
    refs.types.replaceChildren();
    for (const type of graph.relationship_types) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "graph-type-chip";
      button.dataset.typeId = type.id;
      if (interaction.typeId === type.id) button.classList.add("is-active");
      button.innerHTML = `<span class="graph-type-dot" style="background:${type.color}"></span><span>${type.label}</span>${type.directed ? "<small>→</small>" : ""}`;
      button.addEventListener("click", () => {
        interaction.typeId = interaction.typeId === type.id ? "" : type.id;
        interaction.clickConnectFrom = null;
        interaction.connecting = null;
        interaction.dropTarget = null;
        updateRubberBand();
        renderTypes();
        renderNodes();
        updateHint();
      });
      if (!type.builtin) {
        button.title = "右键删除未使用的自定义关系";
        button.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          if (graph.relationship_edges.some((edge) => edge.type_id === type.id)) {
            onNotice("仍有关系使用该自定义线，无法删除。", "warning");
            return;
          }
          graph.relationship_types = graph.relationship_types.filter((item) => item.id !== type.id);
          if (interaction.typeId === type.id) interaction.typeId = graph.relationship_types[0]?.id || "";
          renderTypes();
          emitChange();
        });
      }
      refs.types.appendChild(button);
    }
  }

  function updateHint() {
    const type = typesById().get(interaction.typeId);
    if (refs.hint) {
      if (!type) {
        refs.hint.textContent = "点选一种关系线，再依次点击两个头像即可连接；未选关系线时拖头像是移动位置";
      } else if (interaction.clickConnectFrom) {
        const name = interaction.clickConnectFrom === BOT_NODE_ID
          ? "本机器人"
          : displayName(interaction.clickConnectFrom);
        refs.hint.textContent = `已选「${name}」，再点击另一个头像完成「${type.label}」连线 · 再点一次该头像可取消`;
      } else {
        refs.hint.textContent = `连线中：${type.label}${type.directed ? "（有向）" : ""} · 依次点击两个头像 · 再点该关系线退出连线`;
      }
    }
    root.dataset.mode = interaction.typeId ? "connect" : "select";
  }

  function renderStatus() {
    const memberCount = graph.relationship_nodes.filter((node) => node.kind === "member").length;
    const botCount = graph.relationship_nodes.some((node) => node.kind === "bot") ? 1 : 0;
    refs.status.textContent = `${memberCount} 人 · ${botCount} 机器人 · ${graph.relationship_edges.length} 条关系`;
  }

  function attachAvatar(avatar, userId, fallback) {
    avatar.replaceChildren();
    const text = document.createElement("span");
    text.className = "graph-node-fallback";
    text.textContent = fallback;
    avatar.appendChild(text);
    if (!userId || !/^\d+$/.test(String(userId))) return;
    const image = document.createElement("img");
    image.alt = "";
    image.draggable = false;
    image.referrerPolicy = "no-referrer";
    const params = new URLSearchParams({ b: "qq", nk: String(userId), s: "100" });
    const revision = getAvatarRevision(userId);
    if (revision) params.set("v", String(revision));
    image.src = `https://q1.qlogo.cn/g?${params.toString()}`;
    image.addEventListener("load", () => avatar.classList.add("is-loaded"), { once: true });
    image.addEventListener("error", () => {
      image.remove();
      avatar.classList.remove("is-loaded");
    }, { once: true });
    avatar.appendChild(image);
  }

  function nodeElement(node) {
    const wrap = document.createElement("div");
    wrap.className = `graph-node-wrap graph-node-${node.kind}`;
    wrap.dataset.nodeId = node.id;
    wrap.style.left = `${node.x}px`;
    wrap.style.top = `${node.y}px`;
    if (interaction.selected?.kind === "node" && interaction.selected.id === node.id) {
      wrap.classList.add("is-selected");
    }
    if (interaction.clickConnectFrom === node.id) wrap.classList.add("is-connect-from");
    if (interaction.dropTarget === node.id) wrap.classList.add("is-drop-target");
    const known = node.kind !== "member" || memberMap().has(node.id);
    if (!known) wrap.classList.add("is-left");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "graph-node";
    const avatar = document.createElement("span");
    avatar.className = "graph-node-avatar";
    const bot = getBot();
    const avatarUserId = node.kind === "bot" ? bot.user_id : node.id;
    const label = node.kind === "bot" ? bot.nickname || "本机器人" : displayName(node.id);
    attachAvatar(avatar, avatarUserId, String(label).slice(0, 2));
    button.appendChild(avatar);
    if (node.kind === "bot") {
      button.appendChild(Object.assign(document.createElement("span"), {
        className: "graph-node-badge",
        textContent: "YOU",
      }));
    }
    wrap.appendChild(button);
    if (interaction.clickConnectFrom === node.id) {
      wrap.appendChild(Object.assign(document.createElement("span"), {
        className: "graph-connect-step",
        textContent: "1",
      }));
    }
    wrap.appendChild(Object.assign(document.createElement("span"), {
      className: "graph-node-name",
      textContent: node.kind === "bot" ? "本机器人" : label,
    }));
    if (!known) {
      wrap.appendChild(Object.assign(document.createElement("span"), {
        className: "graph-node-left",
        textContent: "已退群",
      }));
    }
    bindNodePointer(wrap, node.id);
    wrap.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
      selectItem({ kind: "node", id: node.id });
      showMenu(event.clientX, event.clientY, [
        { label: "删除节点", danger: true, run: removeSelection },
      ]);
    });
    return wrap;
  }

  function bindNodePointer(element, nodeId) {
    element.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      hideMenu();
      if (interaction.typeId) {
        if (interaction.clickConnectFrom === nodeId) {
          interaction.clickConnectFrom = null;
          interaction.connecting = null;
          interaction.dropTarget = null;
          updateRubberBand();
          renderNodes();
          updateHint();
          return;
        }
        if (interaction.clickConnectFrom && interaction.clickConnectFrom !== nodeId) {
          addEdge(interaction.clickConnectFrom, nodeId, interaction.typeId);
          interaction.clickConnectFrom = null;
          interaction.connecting = null;
          interaction.dropTarget = null;
          updateRubberBand();
          renderNodes();
          updateHint();
          return;
        }
        interaction.clickConnectFrom = nodeId;
        interaction.connecting = {
          from: nodeId,
          x: event.clientX,
          y: event.clientY,
          startX: event.clientX,
          startY: event.clientY,
          moved: false,
        };
        interaction.dragging = null;
        selectItem({ kind: "node", id: nodeId });
        refs.viewport.setPointerCapture(event.pointerId);
        renderNodes();
        updateHint();
        return;
      }
      selectItem({ kind: "node", id: nodeId });
      const origin = { ...nodeById(nodeId) };
      interaction.dragging = {
        id: nodeId,
        startX: event.clientX,
        startY: event.clientY,
        origin,
        moved: false,
      };
      element.setPointerCapture(event.pointerId);
    });
  }

  function renderNodes() {
    refs.nodes.replaceChildren();
    for (const node of graph.relationship_nodes) refs.nodes.appendChild(nodeElement(node));
    refs.empty.classList.toggle("hidden", Boolean(graph.relationship_nodes.length));
  }

  function parallelOffsets() {
    const typeMap = typesById();
    const buckets = new Map();
    for (const edge of graph.relationship_edges) {
      const key = pairKey(edge.source, edge.target);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(edge);
    }
    const offsets = new Map();
    const slot = 36;
    for (const edges of buckets.values()) {
      const leftId = [edges[0].source, edges[0].target].sort()[0];
      const undirected = [];
      const forward = [];
      const reverse = [];
      for (const edge of edges) {
        const directed = typeMap.get(edge.type_id)?.directed === true;
        if (!directed) undirected.push(edge);
        else if (edge.source === leftId) forward.push(edge);
        else reverse.push(edge);
      }
      undirected.forEach((edge, index) => {
        offsets.set(edge.id, (index - (undirected.length - 1) / 2) * slot);
      });
      const inner = undirected.length ? ((undirected.length - 1) / 2) * slot : 0;
      forward.forEach((edge, index) => {
        offsets.set(edge.id, inner + slot * (index + 1));
      });
      reverse.forEach((edge, index) => {
        offsets.set(edge.id, -(inner + slot * (index + 1)));
      });
    }
    return offsets;
  }

  function pairNormal(sourceId, targetId) {
    const [leftId, rightId] = [sourceId, targetId].sort();
    const left = nodeById(leftId);
    const right = nodeById(rightId);
    if (!left || !right) return { nx: 0, ny: 1 };
    const dx = right.x - left.x;
    const dy = right.y - left.y;
    const len = Math.hypot(dx, dy) || 1;
    return { nx: -dy / len, ny: dx / len };
  }

  function shortenQuadratic(x1, y1, cx, cy, x2, y2, startPad, endPad) {
    const length = Math.hypot(x2 - x1, y2 - y1) || 1;
    const startT = Math.min(0.32, startPad / length);
    const endT = 1 - Math.min(0.32, endPad / length);
    const sx = quad(startT, x1, cx, x2);
    const sy = quad(startT, y1, cy, y2);
    const ex = quad(endT, x1, cx, x2);
    const ey = quad(endT, y1, cy, y2);
    return { sx, sy, ex, ey, cx, cy };
  }

  function quad(t, a, b, c) {
    const u = 1 - t;
    return u * u * a + 2 * u * t * b + t * t * c;
  }

  function markerId(color) {
    return `arrow-${String(color).replace("#", "")}`;
  }

  function renderEdges() {
    const typeMap = typesById();
    const offsets = parallelOffsets();
    const markers = new Set();
    const parts = ["<defs></defs>"];
    for (const edge of graph.relationship_edges) {
      const source = nodeById(edge.source);
      const target = nodeById(edge.target);
      if (!source || !target) continue;
      const type = typeMap.get(edge.type_id);
      const color = type?.color || "#666963";
      const directed = type?.directed === true;
      if (directed) markers.add(color);
      const { nx, ny } = pairNormal(edge.source, edge.target);
      const offset = offsets.get(edge.id) || 0;
      const cx = (source.x + target.x) / 2 + nx * offset;
      const cy = (source.y + target.y) / 2 + ny * offset;
      const curve = shortenQuadratic(
        source.x,
        source.y,
        cx,
        cy,
        target.x,
        target.y,
        NODE_RADIUS,
        NODE_RADIUS + (directed ? 6 : 0),
      );
      const selected = interaction.selected?.kind === "edge" && interaction.selected.id === edge.id;
      const labelT = 0.5;
      const lx = quad(labelT, source.x, cx, target.x);
      const ly = quad(labelT, source.y, cy, target.y);
      const d = `M ${curve.sx} ${curve.sy} Q ${curve.cx} ${curve.cy} ${curve.ex} ${curve.ey}`;
      parts.push(
        `<path data-edge-id="${edge.id}" d="${d}" fill="none" stroke="${color}" stroke-width="${selected ? 3.4 : 2.2}" ${directed ? `marker-end="url(#${markerId(color)})"` : ""} />`,
        `<text data-edge-id="${edge.id}" x="${lx}" y="${ly + 4}" text-anchor="middle" font-size="12">${escapeXml(type?.label || edge.type_id)}</text>`,
      );
    }
    parts.push('<path id="graph-rubber" d="" fill="none" stroke="currentColor" stroke-dasharray="5 4"></path>');
    const markerXml = [...markers].map((color) => (
      `<marker id="${markerId(color)}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"></path></marker>`
    )).join("");
    parts[0] = `<defs>${markerXml}</defs>`;
    refs.edges.innerHTML = parts.join("");
    for (const node of refs.edges.querySelectorAll("[data-edge-id]")) {
      node.addEventListener("pointerdown", (event) => {
        event.stopPropagation();
        hideMenu();
        selectItem({ kind: "edge", id: node.getAttribute("data-edge-id") });
      });
      node.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const id = node.getAttribute("data-edge-id");
        selectItem({ kind: "edge", id });
        const edge = graph.relationship_edges.find((item) => item.id === id);
        const type = typesById().get(edge?.type_id);
        const items = [{ label: "删除关系", danger: true, run: removeSelection }];
        if (type?.directed) items.unshift({ label: "对调方向", run: reverseSelectedEdge });
        showMenu(event.clientX, event.clientY, items);
      });
    }
    updateRubberBand();
  }

  function syncEdgeGeometry() {
    renderEdges();
  }

  function updateRubberBand() {
    const rubber = refs.edges.querySelector("#graph-rubber");
    if (!rubber) return;
    if (!interaction.connecting) {
      rubber.setAttribute("d", "");
      return;
    }
    const from = nodeById(interaction.connecting.from);
    if (!from) {
      rubber.setAttribute("d", "");
      return;
    }
    const world = screenToWorld(interaction.connecting.x, interaction.connecting.y);
    rubber.setAttribute("d", `M ${from.x} ${from.y} L ${world.x} ${world.y}`);
  }

  function escapeXml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function formatPreview() {
    const typeMap = typesById();
    const peer = [];
    const bot = [];
    for (const edge of graph.relationship_edges) {
      const type = typeMap.get(edge.type_id);
      const label = type?.label || edge.type_id;
      const involvesBot = edge.source === BOT_NODE_ID || edge.target === BOT_NODE_ID;
      if (involvesBot) {
        const human = edge.source === BOT_NODE_ID ? edge.target : edge.source;
        if (type?.directed) {
          if (edge.source === BOT_NODE_ID) bot.push(`- 你对群友${displayName(human)}（QQ：${human}）的关系是：${label}`);
          else bot.push(`- ${displayName(human)}（QQ：${human}）对你的关系是：${label}`);
        } else {
          bot.push(`- 你和群友${displayName(human)}（QQ：${human}）的关系是：${label}`);
        }
        continue;
      }
      if (type?.directed) {
        peer.push(`- ${displayName(edge.source)}（QQ：${edge.source}） 对 ${displayName(edge.target)}（QQ：${edge.target}） 的关系是：${label}`);
      } else {
        peer.push(`- ${displayName(edge.source)}（QQ：${edge.source}） 与 ${displayName(edge.target)}（QQ：${edge.target}） 的关系是：${label}`);
      }
    }
    return { peer, bot };
  }

  function renderPreview() {
    const { peer, bot } = formatPreview();
    refs.peerPreview.textContent = peer.join("\n") || "尚无人与人的关系。";
    refs.botPreview.textContent = bot.join("\n") || "尚无你与群友的关系。";
  }

  function renderAll() {
    applyView();
    renderLibrary();
    renderTypes();
    renderNodes();
    renderEdges();
    renderStatus();
    renderPreview();
    updateHint();
  }

  function nodeAtPoint(clientX, clientY) {
    const world = screenToWorld(clientX, clientY);
    let best = null;
    let bestDist = (NODE_RADIUS + 28) ** 2;
    for (const node of graph.relationship_nodes) {
      const dist = (world.x - node.x) ** 2 + (world.y - node.y) ** 2;
      if (dist <= bestDist) {
        best = node.id;
        bestDist = dist;
      }
    }
    return best;
  }

  function finishConnect(event) {
    const gesture = interaction.connecting;
    const from = gesture?.from;
    const moved = Boolean(gesture?.moved);
    interaction.connecting = null;
    interaction.dropTarget = null;
    updateRubberBand();
    if (!from || !interaction.typeId) {
      renderNodes();
      updateHint();
      return;
    }
    const to = nodeAtPoint(event.clientX, event.clientY);
    if (moved && to && to !== from) {
      addEdge(from, to, interaction.typeId);
      interaction.clickConnectFrom = null;
    } else {
      interaction.clickConnectFrom = from;
    }
    renderNodes();
    updateHint();
  }

  function zoomAt(clientX, clientY, nextScale) {
    const world = screenToWorld(clientX, clientY);
    const rect = refs.viewport.getBoundingClientRect();
    view.scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, nextScale));
    view.x = clientX - rect.left - world.x * view.scale;
    view.y = clientY - rect.top - world.y * view.scale;
    applyView();
  }

  refs.viewport.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  refs.viewport.addEventListener("drop", (event) => {
    event.preventDefault();
    const payload = event.dataTransfer.getData("text/plain");
    const point = screenToWorld(event.clientX, event.clientY);
    if (payload === "bot") addBotNode(point);
    else if (payload.startsWith("member:")) addMemberNode(payload.slice(7), point);
  });
  refs.viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomAt(event.clientX, event.clientY, view.scale * (event.deltaY > 0 ? 0.92 : 1.08));
  }, { passive: false });
  refs.viewport.addEventListener("pointerdown", (event) => {
    if (event.button === 2) return;
    if (refs.menu?.contains(event.target) || refs.clearDialog?.contains(event.target)) return;
    hideMenu();
    if (event.button === 1 || interaction.space || event.target === refs.viewport || event.target === refs.world || event.target === refs.edges) {
      refs.viewport.setPointerCapture(event.pointerId);
      interaction.panning = { x: event.clientX - view.x, y: event.clientY - view.y };
      refs.viewport.classList.add("is-panning");
      if (event.target === refs.viewport || event.target === refs.world || event.target === refs.edges) {
        selectItem(null);
        interaction.clickConnectFrom = null;
        interaction.connecting = null;
        interaction.dropTarget = null;
        updateRubberBand();
        renderNodes();
        updateHint();
      }
    }
  });
  refs.viewport.addEventListener("pointermove", (event) => {
    if (interaction.panning) {
      view.x = event.clientX - interaction.panning.x;
      view.y = event.clientY - interaction.panning.y;
      applyView();
      return;
    }
    if (interaction.connecting && !interaction.dragging) {
      const dx = event.clientX - interaction.connecting.startX;
      const dy = event.clientY - interaction.connecting.startY;
      if (Math.hypot(dx, dy) > 12) interaction.connecting.moved = true;
      if (!interaction.connecting.moved) return;
      interaction.connecting.x = event.clientX;
      interaction.connecting.y = event.clientY;
      const dropId = nodeAtPoint(event.clientX, event.clientY);
      const nextDrop = dropId && dropId !== interaction.connecting.from ? dropId : null;
      if (interaction.dropTarget !== nextDrop) {
        interaction.dropTarget = nextDrop;
        renderNodes();
      }
      updateRubberBand();
      return;
    }
    if (interaction.dragging) {
      const dx = event.clientX - interaction.dragging.startX;
      const dy = event.clientY - interaction.dragging.startY;
      if (Math.hypot(dx, dy) > 4) interaction.dragging.moved = true;
      const node = nodeById(interaction.dragging.id);
      if (node) {
        node.x = interaction.dragging.origin.x + dx / view.scale;
        node.y = interaction.dragging.origin.y + dy / view.scale;
        const el = refs.nodes.querySelector(`[data-node-id="${node.id}"]`);
        if (el) {
          el.style.left = `${node.x}px`;
          el.style.top = `${node.y}px`;
        }
        syncEdgeGeometry();
      }
    }
  });
  refs.viewport.addEventListener("pointerup", (event) => {
    const dragged = interaction.dragging;
    if (interaction.connecting && !dragged) finishConnect(event);
    else {
      interaction.connecting = null;
      interaction.dropTarget = null;
      updateRubberBand();
    }
    if (dragged?.moved) emitChange();
    interaction.panning = null;
    interaction.dragging = null;
    refs.viewport.classList.remove("is-panning");
  });
  refs.viewport.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    if (refs.menu?.contains(event.target)) return;
    showMenu(event.clientX, event.clientY, [
      { label: "适应画布", run: fitView },
      { label: "整理布局", run: layoutGraph },
    ]);
  });

  root.querySelector("#graph-fit")?.addEventListener("click", fitView);
  root.querySelector("#graph-delete")?.addEventListener("click", removeSelection);
  root.querySelector("#graph-reverse")?.addEventListener("click", reverseSelectedEdge);
  root.querySelector("#graph-layout")?.addEventListener("click", layoutGraph);
  root.querySelector("#graph-cleanup")?.addEventListener("click", cleanupLeftMembers);
  root.querySelector("#graph-clear")?.addEventListener("click", openClearDialog);
  refs.clearCancel?.addEventListener("click", closeClearDialog);
  refs.clearConfirm?.addEventListener("click", () => {
    closeClearDialog();
    clearGraph();
    onNotice("已清空关系网，保存本群设定后生效。", "success");
  });
  refs.menu?.addEventListener("pointerdown", (event) => event.stopPropagation());
  refs.menu?.addEventListener("click", (event) => event.stopPropagation());
  refs.enabled?.addEventListener("change", () => {
    graph.relationship_injection_enabled = refs.enabled.checked === true;
    emitChange();
  });
  refs.librarySearch?.addEventListener("input", renderLibrary);
  refs.customAdd?.addEventListener("click", () => {
    const label = String(refs.customName?.value || "").trim().slice(0, 16);
    if (!label) {
      onNotice("请填写自定义关系名称。", "warning");
      return;
    }
    if (graph.relationship_types.some((type) => type.label === label)) {
      onNotice("已有同名关系线。", "warning");
      return;
    }
    const customCount = graph.relationship_types.filter((type) => type.builtin !== true).length;
    if (customCount >= MAX_CUSTOM_TYPES) {
      onNotice(`最多 ${MAX_CUSTOM_TYPES} 种自定义关系线。`, "warning");
      return;
    }
    const used = new Set(graph.relationship_types.map((type) => type.id));
    const type = {
      id: allocateId("custom_", used),
      label,
      color: nextCustomColor(),
      builtin: false,
      directed: refs.customDirected?.checked === true,
    };
    graph.relationship_types.push(type);
    refs.customName.value = "";
    refs.customDirected.checked = false;
    interaction.typeId = type.id;
    renderTypes();
    updateHint();
    emitChange();
  });

  const onKeyDown = (event) => {
    if (root.classList.contains("hidden")) return;
    const typing = ["INPUT", "TEXTAREA"].includes(event.target.tagName);
    if (event.code === "Space" && !typing) {
      interaction.space = true;
      event.preventDefault();
    }
    if (typing) return;
    if (["Backspace", "Delete"].includes(event.key)) {
      event.preventDefault();
      removeSelection();
    }
    if (event.key === "Escape") {
      interaction.connecting = null;
      interaction.clickConnectFrom = null;
      interaction.dropTarget = null;
      selectItem(null);
      hideMenu();
      closeClearDialog();
      updateRubberBand();
      renderNodes();
      updateHint();
    }
    if (event.key === "r" || event.key === "R") reverseSelectedEdge();
    if (event.key === "f" || event.key === "F") fitView();
    if (event.key === "l" || event.key === "L") layoutGraph();
    if (event.key === "=" || event.key === "+") zoomAt(
      refs.viewport.getBoundingClientRect().left + refs.viewport.clientWidth / 2,
      refs.viewport.getBoundingClientRect().top + refs.viewport.clientHeight / 2,
      view.scale * 1.1,
    );
    if (event.key === "-") zoomAt(
      refs.viewport.getBoundingClientRect().left + refs.viewport.clientWidth / 2,
      refs.viewport.getBoundingClientRect().top + refs.viewport.clientHeight / 2,
      view.scale * 0.9,
    );
  };
  const onKeyUp = (event) => {
    if (event.code === "Space") interaction.space = false;
  };
  const onDocPointerDown = (event) => {
    if (event.button === 2) return;
    if (!refs.menu || refs.menu.classList.contains("hidden")) return;
    if (refs.menu.contains(event.target)) return;
    if (Date.now() - interaction.menuOpenedAt < 280) return;
    hideMenu();
  };
  document.addEventListener("keydown", onKeyDown);
  document.addEventListener("keyup", onKeyUp);
  document.addEventListener("pointerdown", onDocPointerDown, true);

  applyView();
  renderAll();

  return {
    setGraph,
    getGraph,
    refresh() {
      renderAll();
    },
    show() {
      renderAll();
      window.requestAnimationFrame(fitView);
    },
    destroy() {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
      document.removeEventListener("pointerdown", onDocPointerDown, true);
    },
  };
}
