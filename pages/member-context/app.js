const bridge = window.AstrBotPluginPage;

const state = {
  groups: [],
  selectedGroup: null,
  members: [],
  customIdentityFields: [],
  usageRules: "",
  defaultUsageRules: "",
  memberSearch: "",
  memberPage: 1,
  memberPageSize: 20,
  showConfiguredOnly: false,
  loadingMembers: false,
  resettingProfile: false,
  avatarPreviewEnabled: false,
  avatarVersions: new Map(),
  avatarCheckedIds: new Set(),
  avatarCheckGeneration: 0,
  adminCommandWhitelist: [],
  adminCommandBlacklist: [],
  allowMemberAdminCommands: false,
  injectionEnabled: true,
  profileRevision: 0,
  profileDirty: false,
  checkingProfileStatus: false,
  configDirty: false,
};

const elements = {
  notice: document.getElementById("notice"),
  refreshGroups: document.getElementById("refresh-groups"),
  groupSelect: document.getElementById("group-select"),
  groupCount: document.getElementById("group-count"),
  groupErrors: document.getElementById("group-errors"),
  configMessageWindowSize: document.getElementById("config-message-window-size"),
  configLogDetail: document.getElementById("config-log-detail"),
  configAvatarPreview: document.getElementById("config-avatar-preview"),
  groupPolicyPanel: document.getElementById("group-policy-panel"),
  groupAllowMemberAdmin: document.getElementById("group-allow-member-admin"),
  groupAdminWhitelist: document.getElementById("group-admin-whitelist"),
  groupAdminWhitelistSearch: document.getElementById("group-admin-whitelist-search"),
  groupAdminWhitelistOptions: document.getElementById("group-admin-whitelist-options"),
  groupAdminBlacklist: document.getElementById("group-admin-blacklist"),
  groupAdminBlacklistSearch: document.getElementById("group-admin-blacklist-search"),
  groupAdminBlacklistOptions: document.getElementById("group-admin-blacklist-options"),
  saveGroupPolicy: document.getElementById("save-group-policy"),
  savePluginConfig: document.getElementById("save-plugin-config"),
  emptyState: document.getElementById("empty-state"),
  editor: document.getElementById("editor"),
  selectedGroupName: document.getElementById("selected-group-name"),
  selectedGroupMeta: document.getElementById("selected-group-meta"),
  groupInjectionEnabled: document.getElementById("group-injection-enabled"),
  groupInjectionState: document.getElementById("group-injection-state"),
  refreshMembers: document.getElementById("refresh-members"),
  resetProfile: document.getElementById("reset-profile"),
  resetConfirmation: document.getElementById("reset-confirmation"),
  resetConfirmGroup: document.getElementById("reset-confirm-group"),
  cancelReset: document.getElementById("cancel-reset"),
  confirmReset: document.getElementById("confirm-reset"),
  memberCount: document.getElementById("member-count"),
  memberRefreshTime: document.getElementById("member-refresh-time"),
  memberSearch: document.getElementById("member-search"),
  clearMemberSearch: document.getElementById("clear-member-search"),
  configuredFilter: document.getElementById("configured-filter"),
  memberPageSize: document.getElementById("member-page-size"),
  pageStatus: document.getElementById("page-status"),
  customIdentityFields: document.getElementById("custom-identity-fields"),
  customIdentityFieldInput: document.getElementById("custom-identity-field-input"),
  addCustomIdentityField: document.getElementById("add-custom-identity-field"),
  members: document.getElementById("members"),
  memberPaginationTop: document.getElementById("member-pagination-top"),
  previousPageTop: document.getElementById("previous-page-top"),
  pageNumbersTop: document.getElementById("page-numbers-top"),
  nextPageTop: document.getElementById("next-page-top"),
  memberPagination: document.getElementById("member-pagination"),
  previousPage: document.getElementById("previous-page"),
  pageNumbers: document.getElementById("page-numbers"),
  nextPage: document.getElementById("next-page"),
  usageRules: document.getElementById("usage-rules"),
  resetUsageRules: document.getElementById("reset-usage-rules"),
  previewPrompt: document.getElementById("preview-prompt"),
  saveProfile: document.getElementById("save-profile"),
  promptOutput: document.getElementById("prompt-output"),
};

function showNotice(message, kind = "info") {
  elements.notice.textContent = message || "";
  elements.notice.className = message ? `notice ${kind}` : "notice";
}

function formatRefreshTime(value = new Date()) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(value);
}

function selectedPayload() {
  if (!state.selectedGroup) return null;
  return {
    platform_id: state.selectedGroup.platform_id,
    group_id: state.selectedGroup.group_id,
    group_name: state.selectedGroup.group_name || "",
    members: state.members,
    custom_identity_fields: state.customIdentityFields,
    usage_rules: state.usageRules,
    injection_enabled: state.injectionEnabled,
    admin_command_whitelist: state.adminCommandWhitelist,
    admin_command_blacklist: state.adminCommandBlacklist,
    allow_members_admin_commands: state.allowMemberAdminCommands,
    revision: state.profileRevision,
  };
}

function markProfileDirty() {
  state.profileDirty = true;
}

function markConfigDirty() {
  state.configDirty = true;
}

function applyGroupInjectionState(enabled) {
  state.injectionEnabled = enabled === true;
  elements.groupInjectionEnabled.checked = state.injectionEnabled;
  elements.groupInjectionState.textContent = `INJECTION / ${state.injectionEnabled ? "ON" : "OFF"}`;
}

function setEditorVisible(visible) {
  elements.emptyState.classList.toggle("hidden", visible);
  elements.editor.classList.toggle("hidden", !visible);
}

function renderGroupOptions() {
  const previous = state.selectedGroup?.session_key || elements.groupSelect.value;
  elements.groupSelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "请选择一个群";
  elements.groupSelect.appendChild(placeholder);

  for (const group of state.groups) {
    const option = document.createElement("option");
    option.value = group.session_key;
    const offline = group.available ? "" : "（平台离线）";
    const configured = group.has_profile ? " · 已配置" : "";
    option.textContent = `${group.group_name || `群 ${group.group_id}`} · ${group.group_id}${configured}${offline}`;
    option.disabled = !group.available;
    elements.groupSelect.appendChild(option);
  }

  if (previous && state.groups.some((group) => group.session_key === previous)) {
    elements.groupSelect.value = previous;
  }
  elements.groupCount.textContent = state.groups.length
    ? `发现 ${state.groups.length} 个群会话`
    : "没有发现可用群会话";
}

function renderGroupErrors(errors) {
  elements.groupErrors.replaceChildren();
  for (const item of errors || []) {
    const paragraph = document.createElement("p");
    paragraph.textContent = `${item.platform_id || "平台"}：${item.message || "读取失败"}`;
    elements.groupErrors.appendChild(paragraph);
  }
}

async function loadGroups() {
  elements.refreshGroups.disabled = true;
  try {
    const result = await bridge.apiGet("groups");
    state.groups = Array.isArray(result.groups) ? result.groups : [];
    renderGroupOptions();
    renderGroupErrors(result.errors);
    if (!state.groups.length) {
      showNotice("没有读取到已连接的 OneBot QQ 群。", "warning");
    } else if (!result.errors?.length) {
      showNotice("群列表已刷新。", "success");
    }
  } catch (error) {
    showNotice(error.message || "读取群列表失败。", "error");
  } finally {
    elements.refreshGroups.disabled = false;
  }
}

function applyPluginConfig(config) {
  const messageWindowSize = Number(config?.message_window_size);
  elements.configMessageWindowSize.value = Number.isInteger(messageWindowSize)
    ? String(messageWindowSize)
    : "20";
  elements.configLogDetail.value = config?.log_detail === "全部" ? "全部" : "摘要";
  const avatarPreviewEnabled = config?.avatar_preview_enabled === true;
  const avatarPreviewChanged = state.avatarPreviewEnabled !== avatarPreviewEnabled;
  state.avatarPreviewEnabled = avatarPreviewEnabled;
  elements.configAvatarPreview.checked = avatarPreviewEnabled;
  state.configDirty = false;
  if (avatarPreviewChanged) {
    state.avatarCheckGeneration += 1;
    state.avatarCheckedIds.clear();
    if (state.members.length) renderMembers({ forceAvatarCheck: avatarPreviewEnabled });
  }
}

function memberLabel(userId) {
  const member = state.members.find((item) => String(item.user_id) === String(userId));
  if (!member) return `QQ ${userId}`;
  const roleLabels = { owner: "群主", admin: "管理员", member: "成员" };
  const name = member.card || member.nickname || member.user_id;
  return `${name} · ${member.user_id} · ${roleLabels[member.role] || "成员"}`;
}

function renderQQPolicyList(container, values, removeValue) {
  container.replaceChildren();
  if (!values.length) {
    container.appendChild(createTextElement("span", "muted", "未设置"));
    return;
  }
  for (const userId of values) {
    const chip = document.createElement("span");
    chip.className = "term-chip";
    chip.appendChild(createTextElement("span", "", memberLabel(userId)));
    const remove = createTextElement("button", "chip-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `移除 QQ ${userId}`);
    remove.addEventListener("click", () => removeValue(userId));
    chip.appendChild(remove);
    container.appendChild(chip);
  }
}

function renderAdminCommandLists() {
  renderQQPolicyList(
    elements.groupAdminWhitelist,
    state.adminCommandWhitelist,
    (userId) => {
      state.adminCommandWhitelist = state.adminCommandWhitelist.filter((item) => item !== userId);
      markProfileDirty();
      renderAdminCommandLists();
      populateAdminPolicyPickers();
    },
  );
  renderQQPolicyList(
    elements.groupAdminBlacklist,
    state.adminCommandBlacklist,
    (userId) => {
      state.adminCommandBlacklist = state.adminCommandBlacklist.filter((item) => item !== userId);
      markProfileDirty();
      renderAdminCommandLists();
      populateAdminPolicyPickers();
    },
  );
}

function sortedPolicyMembers() {
  const roleRank = { owner: 0, admin: 1, member: 2 };
  return [...state.members].sort((left, right) => {
    const rank = (roleRank[left.role] ?? 3) - (roleRank[right.role] ?? 3);
    if (rank) return rank;
    return memberLabel(left.user_id).localeCompare(memberLabel(right.user_id), "zh-CN");
  });
}

function memberMatchesPolicySearch(member, query) {
  if (!query) return true;
  return [member.user_id, member.card, member.nickname].some((value) =>
    normalizedSearchValue(value).includes(query));
}

function policyPickerConfigs() {
  return [
    {
      input: elements.groupAdminWhitelistSearch,
      options: elements.groupAdminWhitelistOptions,
      listName: "adminCommandWhitelist",
      otherListName: "adminCommandBlacklist",
    },
    {
      input: elements.groupAdminBlacklistSearch,
      options: elements.groupAdminBlacklistOptions,
      listName: "adminCommandBlacklist",
      otherListName: "adminCommandWhitelist",
    },
  ];
}

function closeAdminPolicyPickers() {
  for (const { input, options } of policyPickerConfigs()) {
    options.classList.add("hidden");
    input.setAttribute("aria-expanded", "false");
  }
}

function renderPolicyPicker(config, open = false) {
  const { input, options, listName, otherListName } = config;
  options.replaceChildren();
  const query = normalizedSearchValue(input.value);
  const matches = sortedPolicyMembers().filter((member) => {
    const userId = String(member.user_id);
    return !state[listName].includes(userId) && memberMatchesPolicySearch(member, query);
  });
  if (!matches.length) {
    options.appendChild(createTextElement(
      "p",
      "member-picker-empty",
      state.members.length ? "没有匹配的可选成员。" : "暂无群成员。",
    ));
  }
  for (const member of matches) {
    const userId = String(member.user_id);
    const option = document.createElement("button");
    option.className = "member-picker-option";
    option.type = "button";
    option.setAttribute("role", "option");
    option.appendChild(createTextElement(
      "span",
      "member-picker-name",
      member.card || member.nickname || userId,
    ));
    const details = [
      `QQ ${userId}`,
      member.card ? `群备注 ${member.card}` : "",
      member.nickname ? `平台昵称 ${member.nickname}` : "",
    ].filter(Boolean).join(" · ");
    option.appendChild(createTextElement("span", "member-picker-meta", details));
    option.addEventListener("click", () => {
      addMemberToPolicy(listName, userId, otherListName);
      input.value = "";
      closeAdminPolicyPickers();
    });
    options.appendChild(option);
  }
  options.classList.toggle("hidden", !open);
  input.setAttribute("aria-expanded", String(open));
}

function populateAdminPolicyPickers(openInput = null) {
  for (const config of policyPickerConfigs()) {
    renderPolicyPicker(config, config.input === openInput);
  }
}

function addMemberToPolicy(listName, userId, otherListName) {
  if (!userId) return;
  state[otherListName] = state[otherListName].filter((item) => item !== userId);
  if (!state[listName].includes(userId)) state[listName].push(userId);
  markProfileDirty();
  renderAdminCommandLists();
  populateAdminPolicyPickers();
}

function applyGroupPolicy(profile) {
  state.adminCommandWhitelist = Array.isArray(profile?.admin_command_whitelist)
    ? profile.admin_command_whitelist.map(String).filter((item) => /^\d+$/.test(item))
    : [];
  state.adminCommandBlacklist = Array.isArray(profile?.admin_command_blacklist)
    ? profile.admin_command_blacklist.map(String).filter((item) => /^\d+$/.test(item))
    : [];
  state.allowMemberAdminCommands = profile?.allow_members_admin_commands === true;
  elements.groupAllowMemberAdmin.checked = state.allowMemberAdminCommands;
  renderAdminCommandLists();
  populateAdminPolicyPickers();
}

async function loadPluginConfig({ force = false } = {}) {
  if (state.configDirty && !force) return;
  try {
    const result = await bridge.apiGet("config");
    applyPluginConfig(result);
  } catch (error) {
    showNotice(error.message || "读取插件配置失败。", "error");
  }
}

async function savePluginConfig() {
  const messageWindowSize = Number(elements.configMessageWindowSize.value);
  if (!Number.isInteger(messageWindowSize) || messageWindowSize < 1 || messageWindowSize > 200) {
    showNotice("动态成员消息窗口数量必须是 1～200 的整数。", "warning");
    elements.configMessageWindowSize.focus();
    return;
  }

  elements.savePluginConfig.disabled = true;
  try {
    const result = await bridge.apiPost("config", {
      message_window_size: messageWindowSize,
      log_detail: elements.configLogDetail.value,
      avatar_preview_enabled: elements.configAvatarPreview.checked,
    });
    applyPluginConfig(result);
    showNotice("插件配置已保存，页面展示与新的 LLM 请求会使用最新设置。", "success");
  } catch (error) {
    showNotice(error.message || "保存插件配置失败。", "error");
  } finally {
    elements.savePluginConfig.disabled = false;
  }
}

function createTextElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text || "";
  return element;
}

function normalizedSearchValue(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function memberMatchesSearch(member, query) {
  if (!query) return true;
  return [member.nickname, member.user_id, member.card].some((value) =>
    normalizedSearchValue(value).includes(query),
  );
}

function hasConfiguredIdentity(member) {
  const standardFields = [member.aliases, member.real_names, member.nicknames];
  return (
    standardFields.some(
      (values) =>
        Array.isArray(values) && values.some((value) => String(value || "").trim()),
    )
    || Object.values(member.custom_fields || {}).some(
      (values) =>
        Array.isArray(values) && values.some((value) => String(value || "").trim()),
    )
    || Boolean(String(member.note || "").trim())
  );
}

function filteredMembers() {
  const query = normalizedSearchValue(state.memberSearch);
  return state.members.filter(
    (member) =>
      memberMatchesSearch(member, query)
      && (!state.showConfiguredOnly || hasConfiguredIdentity(member)),
  );
}

function renderTerms(member, field, termContainer) {
  termContainer.replaceChildren();
  member[field] = Array.isArray(member[field]) ? member[field] : [];
  for (const term of member[field]) {
    const chip = document.createElement("span");
    chip.className = "term-chip";
    chip.appendChild(createTextElement("span", "", term));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.setAttribute("aria-label", `移除 ${term}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      member[field] = member[field].filter((item) => item !== term);
      markProfileDirty();
      renderTerms(member, field, termContainer);
    });
    chip.appendChild(remove);
    termContainer.appendChild(chip);
  }
}

function addTerm(member, field, input, termContainer) {
  const term = input.value.trim();
  if (!term) return;
  member[field] = Array.isArray(member[field]) ? member[field] : [];
  if (!member[field].some((item) => item.toLocaleLowerCase() === term.toLocaleLowerCase())) {
    member[field].push(term);
    markProfileDirty();
  }
  input.value = "";
  renderTerms(member, field, termContainer);
}

function customFieldValues(member, label) {
  if (!member.custom_fields || typeof member.custom_fields !== "object") {
    member.custom_fields = {};
  }
  member.custom_fields[label] = Array.isArray(member.custom_fields[label])
    ? member.custom_fields[label]
    : [];
  return member.custom_fields[label];
}

function renderCustomFieldTerms(member, label, termContainer) {
  termContainer.replaceChildren();
  for (const term of customFieldValues(member, label)) {
    const chip = document.createElement("span");
    chip.className = "term-chip";
    chip.appendChild(createTextElement("span", "", term));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.setAttribute("aria-label", `移除 ${label}：${term}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      member.custom_fields[label] = customFieldValues(member, label).filter(
        (item) => item !== term,
      );
      markProfileDirty();
      renderCustomFieldTerms(member, label, termContainer);
    });
    chip.appendChild(remove);
    termContainer.appendChild(chip);
  }
}

function addCustomFieldTerm(member, label, input, termContainer) {
  const term = input.value.trim();
  if (!term) return;
  const values = customFieldValues(member, label);
  if (!values.some((item) => item.toLocaleLowerCase() === term.toLocaleLowerCase())) {
    values.push(term);
    markProfileDirty();
  }
  input.value = "";
  renderCustomFieldTerms(member, label, termContainer);
}

function createCustomFieldEditor(member, index, label, fieldIndex) {
  const wrapper = document.createElement("div");
  wrapper.className = "term-editor custom-field-editor";
  const inputId = `custom-field-input-${index}-${fieldIndex}`;
  const fieldLabel = createTextElement("label", "field-label", label);
  fieldLabel.htmlFor = inputId;
  wrapper.appendChild(fieldLabel);

  const editor = document.createElement("div");
  editor.className = "term-control";
  const termContainer = document.createElement("div");
  termContainer.className = "term-list";
  renderCustomFieldTerms(member, label, termContainer);
  const input = document.createElement("input");
  input.id = inputId;
  input.className = "text-input term-input";
  input.placeholder = `输入${label}`;
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCustomFieldTerm(member, label, input, termContainer);
    }
  });
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "button button-small button-secondary";
  addButton.textContent = "添加";
  addButton.addEventListener("click", () =>
    addCustomFieldTerm(member, label, input, termContainer),
  );
  editor.append(termContainer, input, addButton);
  wrapper.appendChild(editor);
  return wrapper;
}

function renderCustomIdentityFields() {
  elements.customIdentityFields.replaceChildren();
  for (const label of state.customIdentityFields) {
    const chip = document.createElement("span");
    chip.className = "term-chip custom-field-chip";
    chip.appendChild(createTextElement("span", "", label));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.setAttribute("aria-label", `移除本群字段 ${label}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.customIdentityFields = state.customIdentityFields.filter(
        (item) => item !== label,
      );
      markProfileDirty();
      renderCustomIdentityFields();
      renderMembers();
    });
    chip.appendChild(remove);
    elements.customIdentityFields.appendChild(chip);
  }
}

function addCustomIdentityField() {
  const label = elements.customIdentityFieldInput.value.trim();
  if (!label) return;
  if (state.customIdentityFields.some((item) => item.toLocaleLowerCase() === label.toLocaleLowerCase())) {
    showNotice(`字段“${label}”已经存在。`, "warning");
    return;
  }
  if (state.customIdentityFields.length >= 16) {
    showNotice("每个群最多添加 16 个自定义身份字段。", "warning");
    return;
  }
  state.customIdentityFields.push(label.slice(0, 32));
  markProfileDirty();
  elements.customIdentityFieldInput.value = "";
  renderCustomIdentityFields();
  renderMembers();
}

function createTermEditor(member, index, config) {
  const wrapper = document.createElement("div");
  wrapper.className = "term-editor";
  const label = createTextElement("label", "field-label", config.label);
  label.htmlFor = `${config.inputPrefix}-input-${index}`;
  wrapper.appendChild(label);

  const editor = document.createElement("div");
  editor.className = "term-control";
  const termContainer = document.createElement("div");
  termContainer.className = "term-list";
  renderTerms(member, config.field, termContainer);
  const input = document.createElement("input");
  input.id = `${config.inputPrefix}-input-${index}`;
  input.className = "text-input term-input";
  input.placeholder = config.placeholder;
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addTerm(member, config.field, input, termContainer);
    }
  });
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "button button-small button-secondary";
  addButton.textContent = "添加";
  addButton.addEventListener("click", () =>
    addTerm(member, config.field, input, termContainer),
  );
  editor.append(termContainer, input, addButton);
  wrapper.appendChild(editor);
  return wrapper;
}

function avatarImageUrl(userId, revision) {
  const params = new URLSearchParams({
    b: "qq",
    nk: String(userId),
    s: "100",
    v: revision,
  });
  return `https://q1.qlogo.cn/g?${params.toString()}`;
}

function attachAvatarImage(avatar, userId, revision) {
  if (!state.avatarPreviewEnabled || !revision) return;
  const currentImage = avatar.querySelector(".member-avatar-image");
  if (avatar.dataset.avatarRevision === revision && currentImage) return;

  currentImage?.remove();
  avatar.classList.remove("avatar-loaded");
  avatar.dataset.avatarRevision = revision;

  const image = document.createElement("img");
  image.className = "member-avatar-image";
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.referrerPolicy = "no-referrer";
  image.addEventListener(
    "load",
    () => {
      if (avatar.contains(image)) avatar.classList.add("avatar-loaded");
    },
    { once: true },
  );
  image.addEventListener(
    "error",
    () => {
      if (!avatar.contains(image)) return;
      avatar.classList.remove("avatar-loaded");
      image.remove();
    },
    { once: true },
  );
  image.src = avatarImageUrl(userId, revision);
  avatar.appendChild(image);
}

function updateVisibleAvatar(userId, revision) {
  for (const avatar of elements.members.querySelectorAll(".member-avatar")) {
    if (avatar.dataset.userId === userId) {
      attachAvatarImage(avatar, userId, revision);
    }
  }
}

async function checkVisibleAvatarUpdates(pageMembers, { force = false } = {}) {
  if (!state.avatarPreviewEnabled || !pageMembers.length) return;
  const allUserIds = [...new Set(
    pageMembers
      .map((member) => String(member.user_id || ""))
      .filter((userId) => /^\d+$/.test(userId)),
  )];
  const userIds = force
    ? allUserIds
    : allUserIds.filter((userId) => !state.avatarCheckedIds.has(userId));
  if (!userIds.length) return;

  for (const userId of userIds) state.avatarCheckedIds.add(userId);
  const generation = state.avatarCheckGeneration;
  try {
    const result = await bridge.apiPost("avatars/check", { user_ids: userIds });
    if (generation !== state.avatarCheckGeneration) return;
    if (result?.enabled !== true) {
      state.avatarPreviewEnabled = false;
      elements.configAvatarPreview.checked = false;
      state.avatarCheckedIds.clear();
      renderMembers();
      return;
    }
    for (const avatar of Array.isArray(result.avatars) ? result.avatars : []) {
      const userId = String(avatar?.user_id || "");
      const revision = String(avatar?.revision || "");
      if (!avatar?.available || !/^\d+$/.test(userId) || !revision) continue;
      state.avatarVersions.set(userId, revision);
      updateVisibleAvatar(userId, revision);
    }
  } catch (error) {
    for (const userId of userIds) state.avatarCheckedIds.delete(userId);
    console.warn("头像更新校验失败：", error);
  }
}

function renderMember(member, index) {
  const card = document.createElement("article");
  card.className = "member-card";
  card.dataset.memberId = member.user_id;

  const identity = document.createElement("div");
  identity.className = "member-identity";
  const avatar = createTextElement(
    "div",
    "member-avatar",
    (member.nickname || member.user_id).slice(0, 2),
  );
  avatar.dataset.userId = String(member.user_id);
  const avatarRevision = state.avatarVersions.get(String(member.user_id));
  if (state.avatarPreviewEnabled && avatarRevision) {
    attachAvatarImage(avatar, String(member.user_id), avatarRevision);
  }
  identity.appendChild(avatar);
  const identityText = document.createElement("div");
  identityText.className = "identity-text";
  identityText.appendChild(
    createTextElement(
      "strong",
      "member-nickname",
      `平台昵称：${member.nickname || "未设置"}`,
    ),
  );
  identityText.appendChild(createTextElement("span", "member-id", `QQ：${member.user_id}`));
  if (member.card) {
    identityText.appendChild(
      createTextElement(
        "span",
        "member-platform-meta",
        `群名片（可用于识别成员）：${member.card}`,
      ),
    );
  }
  identity.appendChild(identityText);
  card.appendChild(identity);

  const form = document.createElement("div");
  form.className = "member-form";
  for (const config of [
    {
      field: "aliases",
      label: "外号（可添加多个）",
      placeholder: "例如：A哥",
      inputPrefix: "alias",
    },
    {
      field: "real_names",
      label: "真名（可添加多个）",
      placeholder: "例如：Tony Wang",
      inputPrefix: "real-name",
    },
    {
      field: "nicknames",
      label: "昵称（可添加多个）",
      placeholder: "例如：老王",
      inputPrefix: "nickname",
    },
  ]) {
    form.appendChild(createTermEditor(member, index, config));
  }
  for (const [fieldIndex, label] of state.customIdentityFields.entries()) {
    form.appendChild(createCustomFieldEditor(member, index, label, fieldIndex));
  }

  const noteLabel = createTextElement("label", "field-label note-label", "补充说明");
  noteLabel.htmlFor = `note-input-${index}`;
  form.appendChild(noteLabel);
  const noteInput = document.createElement("textarea");
  noteInput.id = `note-input-${index}`;
  noteInput.className = "text-input note-input";
  noteInput.rows = 2;
  noteInput.placeholder = "例如：实际姓名是 Tony，负责项目答疑";
  noteInput.value = member.note || "";
  noteInput.addEventListener("input", () => {
    member.note = noteInput.value;
    markProfileDirty();
  });
  form.appendChild(noteInput);
  card.appendChild(form);
  return card;
}

function paginationItems(totalPages, currentPage) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "ellipsis", totalPages];
  }
  if (currentPage >= totalPages - 3) {
    return [
      1,
      "ellipsis",
      totalPages - 4,
      totalPages - 3,
      totalPages - 2,
      totalPages - 1,
      totalPages,
    ];
  }
  return [
    1,
    "ellipsis",
    currentPage - 1,
    currentPage,
    currentPage + 1,
    "ellipsis",
    totalPages,
  ];
}

function renderPageNumbers(container, totalPages) {
  container.replaceChildren();
  for (const item of paginationItems(totalPages, state.memberPage)) {
    if (item === "ellipsis") {
      container.appendChild(createTextElement("span", "page-ellipsis", "…"));
      continue;
    }
    const button = createTextElement(
      "button",
      "button button-small page-button",
      String(item),
    );
    button.type = "button";
    button.dataset.page = String(item);
    button.setAttribute("aria-label", `跳转到第 ${item} 页`);
    if (item === state.memberPage) {
      button.classList.add("active");
      button.setAttribute("aria-current", "page");
    }
    button.addEventListener("click", () => {
      state.memberPage = item;
      renderMembers();
    });
    container.appendChild(button);
  }
}

function renderPagination(totalItems) {
  const totalPages = Math.max(1, Math.ceil(totalItems / state.memberPageSize));
  state.memberPage = Math.min(Math.max(state.memberPage, 1), totalPages);
  const hasPagination = totalItems > 0 && totalPages > 1;
  elements.pageStatus.textContent = totalItems
    ? `第 ${state.memberPage} / ${totalPages} 页`
    : "";

  for (const controls of [
    {
      container: elements.memberPaginationTop,
      previous: elements.previousPageTop,
      pageNumbers: elements.pageNumbersTop,
      next: elements.nextPageTop,
    },
    {
      container: elements.memberPagination,
      previous: elements.previousPage,
      pageNumbers: elements.pageNumbers,
      next: elements.nextPage,
    },
  ]) {
    controls.container.classList.toggle("hidden", !hasPagination);
    controls.previous.disabled = state.memberPage <= 1;
    controls.next.disabled = state.memberPage >= totalPages;
    renderPageNumbers(controls.pageNumbers, totalPages);
  }
}

function updateConfiguredFilter() {
  elements.configuredFilter.classList.toggle("active", state.showConfiguredOnly);
  elements.configuredFilter.setAttribute(
    "aria-pressed",
    String(state.showConfiguredOnly),
  );
}

function renderMembers({ scrollToFirst = false, forceAvatarCheck = false } = {}) {
  const visibleMembers = filteredMembers();
  const totalPages = Math.max(1, Math.ceil(visibleMembers.length / state.memberPageSize));
  state.memberPage = Math.min(Math.max(state.memberPage, 1), totalPages);
  const start = (state.memberPage - 1) * state.memberPageSize;
  const pageMembers = visibleMembers.slice(start, start + state.memberPageSize);
  elements.members.replaceChildren();
  renderPagination(visibleMembers.length);
  if (!state.members.length) {
    elements.memberCount.textContent = "当前群没有可展示的成员";
  } else {
    const filters = [];
    if (state.memberSearch.trim()) filters.push(`搜索匹配 ${visibleMembers.length}`);
    if (state.showConfiguredOnly) filters.push(`已配置筛选 ${visibleMembers.length}`);
    elements.memberCount.textContent = filters.length
      ? `${filters.join(" · ")} / 共 ${state.members.length} 位群成员`
      : `已刷新 ${state.members.length} 位群成员`;
  }

  if (!visibleMembers.length) {
    const emptyText = state.showConfiguredOnly && !state.memberSearch.trim()
      ? "当前没有已配置身份的成员。"
      : `没有找到与“${state.memberSearch.trim()}”匹配的成员。可搜索平台昵称、QQ号或群名片。`;
    const empty = createTextElement(
      "p",
      "members-empty",
      emptyText,
    );
    elements.members.appendChild(empty);
    return;
  }

  for (const member of pageMembers) {
    const originalIndex = state.members.indexOf(member);
    elements.members.appendChild(renderMember(member, originalIndex));
  }

  if (state.avatarPreviewEnabled) {
    void checkVisibleAvatarUpdates(pageMembers, { force: forceAvatarCheck });
  }

  if (scrollToFirst) {
    requestAnimationFrame(() => {
      elements.members.querySelector(".member-card")?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  }
}

async function refreshMembers({ quiet = false } = {}) {
  if (!state.selectedGroup) return;
  state.loadingMembers = true;
  elements.refreshMembers.disabled = true;
  if (!quiet) showNotice("正在从 OneBot 刷新群成员信息…", "info");
  try {
    const result = await bridge.apiGet("members", {
      platform_id: state.selectedGroup.platform_id,
      group_id: state.selectedGroup.group_id,
    });
    state.members = Array.isArray(result.members) ? result.members : [];
    state.customIdentityFields = Array.isArray(result.custom_identity_fields)
      ? result.custom_identity_fields
      : [];
    state.memberSearch = "";
    state.memberPage = 1;
    state.showConfiguredOnly = false;
    elements.memberSearch.value = "";
    updateConfiguredFilter();
    state.defaultUsageRules = result.default_usage_rules || state.defaultUsageRules;
    state.usageRules = result.usage_rules || state.defaultUsageRules;
    state.profileRevision = Number(result.revision) || 0;
    state.profileDirty = false;
    applyGroupInjectionState(result.injection_enabled !== false);
    applyGroupPolicy(result);
    elements.usageRules.value = state.usageRules;
    renderCustomIdentityFields();
    if (result.group_name) state.selectedGroup.group_name = result.group_name;
    elements.selectedGroupName.textContent = state.selectedGroup.group_name || `群 ${state.selectedGroup.group_id}`;
    renderMembers({ forceAvatarCheck: state.avatarPreviewEnabled });
    elements.memberRefreshTime.textContent = `最近读取：${formatRefreshTime()}`;
    if (!quiet) {
      showNotice(
        `已刷新 ${state.members.length} 位群成员；平台昵称、群名片等资料已更新，已配置身份字段会按 QQ 号匹配保留。请保存本群设定以写入最新成员信息。`,
        "success",
      );
    }
  } catch (error) {
    showNotice(error.message || "刷新群成员信息失败。", "error");
  } finally {
    state.loadingMembers = false;
    elements.refreshMembers.disabled = false;
  }
}

async function checkProfileStatus() {
  if (!state.selectedGroup || state.loadingMembers || state.checkingProfileStatus) return;
  state.checkingProfileStatus = true;
  try {
    const result = await bridge.apiGet("profile/status", {
      platform_id: state.selectedGroup.platform_id,
      group_id: state.selectedGroup.group_id,
    });
    const remoteRevision = Number(result.revision) || 0;
    if (remoteRevision <= state.profileRevision) return;
    if (state.profileDirty) {
      showNotice("本群资料已由群指令更新；请刷新后再继续编辑。", "warning");
      return;
    }
    await refreshMembers({ quiet: true });
    showNotice("已同步群内指令产生的最新身份资料。", "success");
  } catch (error) {
    console.warn("检查群身份资料版本失败：", error);
  } finally {
    state.checkingProfileStatus = false;
  }
}

async function previewPrompt() {
  const payload = selectedPayload();
  if (!payload) return;
  elements.previewPrompt.disabled = true;
  try {
    const result = await bridge.apiPost("preview", payload);
    elements.promptOutput.textContent =
      result.prompt || "当前没有可注入的成员资料。";
    showNotice("Prompt 预览已更新。", "success");
  } catch (error) {
    showNotice(error.message || "生成 Prompt 失败。", "error");
  } finally {
    elements.previewPrompt.disabled = false;
  }
}

async function saveProfile() {
  const payload = selectedPayload();
  if (!payload) return;
  elements.saveProfile.disabled = true;
  elements.saveGroupPolicy.disabled = true;
  try {
    const result = await bridge.apiPost("profiles", payload);
    elements.promptOutput.textContent =
      result.prompt || "当前没有可注入的成员资料。";
    if (result.default_usage_rules) {
      state.defaultUsageRules = result.default_usage_rules;
    }
    if (result.usage_rules) {
      state.usageRules = result.usage_rules;
      elements.usageRules.value = state.usageRules;
    }
    if (Array.isArray(result.custom_identity_fields)) {
      state.customIdentityFields = result.custom_identity_fields;
      renderCustomIdentityFields();
      renderMembers();
    }
    state.profileRevision = Number(result.revision) || state.profileRevision;
    state.profileDirty = false;
    applyGroupInjectionState(result.injection_enabled !== false);
    applyGroupPolicy(result);
    const selected = state.groups.find((group) => group.session_key === state.selectedGroup.session_key);
    if (selected) {
      selected.has_profile = Boolean(
        state.usageRules.trim() !== state.defaultUsageRules.trim()
        || state.members.some((member) => hasConfiguredIdentity(member))
        || state.adminCommandWhitelist.length
        || state.adminCommandBlacklist.length
        || state.allowMemberAdminCommands
      );
      selected.member_count = state.members.length;
      selected.revision = state.profileRevision;
      selected.injection_enabled = state.injectionEnabled;
    }
    renderGroupOptions();
    elements.groupSelect.value = state.selectedGroup.session_key;
    showNotice(
      `已保存 ${result.member_count} 位成员，已配置 ${result.configured_member_count || 0} 位；实际只注入最近 ${result.message_window_size || "配置的"} 条消息中的发言成员，以及消息中提到的已配置成员。${result.usage_rules_customized ? "已修改本群使用规则。" : "当前使用默认规则。"}`,
      "success",
    );
  } catch (error) {
    showNotice(error.message || "保存设定失败。", "error");
  } finally {
    elements.saveProfile.disabled = false;
    elements.saveGroupPolicy.disabled = false;
  }
}

function openResetConfirmation() {
  if (!state.selectedGroup || state.resettingProfile) return;
  const groupLabel = state.selectedGroup.group_name || `群 ${state.selectedGroup.group_id}`;
  elements.resetConfirmGroup.textContent = `当前群：${groupLabel}（${state.selectedGroup.group_id}）`;
  elements.resetConfirmation.classList.remove("hidden");
  elements.resetConfirmation.setAttribute("aria-hidden", "false");
  elements.confirmReset.focus();
}

function closeResetConfirmation({ restoreFocus = true } = {}) {
  elements.resetConfirmation.classList.add("hidden");
  elements.resetConfirmation.setAttribute("aria-hidden", "true");
  if (restoreFocus) elements.resetProfile.focus();
}

async function performResetProfile() {
  if (!state.selectedGroup || state.resettingProfile) return;
  const groupLabel = state.selectedGroup.group_name || `群 ${state.selectedGroup.group_id}`;
  state.resettingProfile = true;
  elements.resetProfile.disabled = true;
  elements.cancelReset.disabled = true;
  elements.confirmReset.disabled = true;
  closeResetConfirmation({ restoreFocus: false });
  showNotice("正在重置当前群设定…", "info");
  try {
    const result = await bridge.apiPost("reset", {
      platform_id: state.selectedGroup.platform_id,
      group_id: state.selectedGroup.group_id,
      group_name: state.selectedGroup.group_name || "",
      members: state.members,
      revision: state.profileRevision,
    });
    state.members = Array.isArray(result.members) ? result.members : [];
    state.defaultUsageRules = result.default_usage_rules || state.defaultUsageRules;
    state.usageRules = result.usage_rules || state.defaultUsageRules;
    state.profileRevision = Number(result.revision) || state.profileRevision;
    state.profileDirty = false;
    applyGroupInjectionState(result.injection_enabled !== false);
    applyGroupPolicy(result);
    state.memberSearch = "";
    state.memberPage = 1;
    state.showConfiguredOnly = false;
    elements.usageRules.value = state.usageRules;
    elements.memberSearch.value = "";
    updateConfiguredFilter();
    if (Array.isArray(result.custom_identity_fields)) {
      state.customIdentityFields = result.custom_identity_fields;
      renderCustomIdentityFields();
    }
    elements.promptOutput.textContent = "保存或预览后显示。";
    renderMembers();
    const selected = state.groups.find(
      (group) => group.session_key === state.selectedGroup.session_key,
    );
    if (selected) {
      selected.has_profile = Boolean(
        state.adminCommandWhitelist.length
        || state.adminCommandBlacklist.length
        || state.allowMemberAdminCommands
      );
      selected.member_count = state.members.length;
      selected.revision = state.profileRevision;
      selected.injection_enabled = state.injectionEnabled;
    }
    renderGroupOptions();
    elements.groupSelect.value = state.selectedGroup.session_key;
    showNotice(`已完全重置“${groupLabel}”的成员身份设定。`, "success");
  } catch (error) {
    showNotice(error.message || "重置当前群设定失败。", "error");
  } finally {
    state.resettingProfile = false;
    elements.resetProfile.disabled = false;
    elements.cancelReset.disabled = false;
    elements.confirmReset.disabled = false;
  }
}

function selectGroup() {
  const selected = state.groups.find((group) => group.session_key === elements.groupSelect.value);
  state.selectedGroup = selected || null;
  state.members = [];
  state.usageRules = "";
  state.memberSearch = "";
  state.memberPage = 1;
  state.showConfiguredOnly = false;
  state.profileRevision = Number(selected?.revision) || 0;
  state.profileDirty = false;
  state.adminCommandWhitelist = [];
  state.adminCommandBlacklist = [];
  state.allowMemberAdminCommands = false;
  elements.groupAdminWhitelistSearch.value = "";
  elements.groupAdminBlacklistSearch.value = "";
  closeAdminPolicyPickers();
  applyGroupPolicy({});
  applyGroupInjectionState(selected?.injection_enabled !== false);
  state.avatarCheckGeneration += 1;
  state.avatarCheckedIds.clear();
  elements.usageRules.value = "";
  elements.memberSearch.value = "";
  elements.memberRefreshTime.textContent = "最近读取：尚未读取";
  updateConfiguredFilter();
  elements.promptOutput.textContent = "保存或预览后显示。";
  elements.groupPolicyPanel.classList.toggle("hidden", !selected);
  if (!selected) {
    setEditorVisible(false);
    return;
  }
  setEditorVisible(true);
  elements.selectedGroupName.textContent = selected.group_name || `群 ${selected.group_id}`;
  elements.selectedGroupMeta.textContent = `${selected.platform_id} · 群号 ${selected.group_id}`;
  renderMembers();
  refreshMembers();
}

async function init() {
  await bridge.ready();
  elements.refreshGroups.addEventListener("click", loadGroups);
  elements.groupSelect.addEventListener("change", selectGroup);
  elements.savePluginConfig.addEventListener("click", savePluginConfig);
  for (const control of [
    elements.configMessageWindowSize,
    elements.configLogDetail,
    elements.configAvatarPreview,
  ]) {
    control.addEventListener("input", markConfigDirty);
  }
  elements.groupAllowMemberAdmin.addEventListener("change", () => {
    state.allowMemberAdminCommands = elements.groupAllowMemberAdmin.checked;
    markProfileDirty();
  });
  for (const config of policyPickerConfigs()) {
    const openPicker = () => populateAdminPolicyPickers(config.input);
    config.input.addEventListener("focus", openPicker);
    config.input.addEventListener("click", openPicker);
    config.input.addEventListener("input", openPicker);
  }
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element) || !event.target.closest(".member-picker")) {
      closeAdminPolicyPickers();
    }
  });
  elements.saveGroupPolicy.addEventListener("click", saveProfile);
  elements.refreshMembers.addEventListener("click", refreshMembers);
  elements.resetProfile.addEventListener("click", openResetConfirmation);
  elements.cancelReset.addEventListener("click", () => closeResetConfirmation());
  elements.confirmReset.addEventListener("click", performResetProfile);
  elements.resetConfirmation.addEventListener("click", (event) => {
    if (event.target === elements.resetConfirmation) closeResetConfirmation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAdminPolicyPickers();
    if (!elements.resetConfirmation.classList.contains("hidden")) closeResetConfirmation();
  });
  elements.previewPrompt.addEventListener("click", previewPrompt);
  elements.saveProfile.addEventListener("click", saveProfile);
  elements.usageRules.addEventListener("input", () => {
    state.usageRules = elements.usageRules.value;
    markProfileDirty();
  });
  elements.groupInjectionEnabled.addEventListener("change", () => {
    applyGroupInjectionState(elements.groupInjectionEnabled.checked);
    markProfileDirty();
  });
  elements.resetUsageRules.addEventListener("click", () => {
    state.usageRules = state.defaultUsageRules;
    elements.usageRules.value = state.usageRules;
    markProfileDirty();
    showNotice("使用规则已恢复为默认内容；请保存本群设定后生效。", "success");
  });
  elements.addCustomIdentityField.addEventListener("click", addCustomIdentityField);
  elements.customIdentityFieldInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCustomIdentityField();
    }
  });
  elements.memberSearch.addEventListener("input", () => {
    state.memberSearch = elements.memberSearch.value;
    state.memberPage = 1;
    renderMembers();
  });
  elements.memberSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const visibleMembers = filteredMembers();
    renderMembers({ scrollToFirst: true });
    showNotice(
      visibleMembers.length
        ? `已定位到 ${visibleMembers.length} 位匹配成员。`
        : "没有找到匹配成员。",
      visibleMembers.length ? "success" : "warning",
    );
  });
  elements.clearMemberSearch.addEventListener("click", () => {
    state.memberSearch = "";
    state.memberPage = 1;
    elements.memberSearch.value = "";
    renderMembers();
    elements.memberSearch.focus();
  });
  elements.configuredFilter.addEventListener("click", () => {
    state.showConfiguredOnly = !state.showConfiguredOnly;
    state.memberPage = 1;
    updateConfiguredFilter();
    renderMembers();
  });
  elements.memberPageSize.addEventListener("change", () => {
    state.memberPageSize = Number(elements.memberPageSize.value) || 20;
    state.memberPage = 1;
    renderMembers();
  });
  elements.previousPage.addEventListener("click", () => {
    if (state.memberPage <= 1) return;
    state.memberPage -= 1;
    renderMembers();
  });
  elements.nextPage.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(filteredMembers().length / state.memberPageSize));
    if (state.memberPage >= totalPages) return;
    state.memberPage += 1;
    renderMembers();
  });
  elements.previousPageTop.addEventListener("click", () => {
    if (state.memberPage <= 1) return;
    state.memberPage -= 1;
    renderMembers();
  });
  elements.nextPageTop.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(filteredMembers().length / state.memberPageSize));
    if (state.memberPage >= totalPages) return;
    state.memberPage += 1;
    renderMembers();
  });
  updateConfiguredFilter();
  await Promise.all([loadPluginConfig(), loadGroups()]);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      void loadPluginConfig();
      void checkProfileStatus();
    }
  });
  window.setInterval(() => {
    void loadPluginConfig();
    void checkProfileStatus();
  }, 15000);
}

init().catch((error) => showNotice(error.message || "页面初始化失败。", "error"));
