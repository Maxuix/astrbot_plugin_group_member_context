const bridge = window.AstrBotPluginPage;

const state = {
  groups: [],
  selectedGroup: null,
  members: [],
  customIdentityFields: [],
  customPrompt: "",
  memberSearch: "",
  memberPage: 1,
  memberPageSize: 20,
  showConfiguredOnly: false,
  loadingMembers: false,
  resettingProfile: false,
};

const elements = {
  notice: document.getElementById("notice"),
  refreshGroups: document.getElementById("refresh-groups"),
  groupSelect: document.getElementById("group-select"),
  groupCount: document.getElementById("group-count"),
  groupErrors: document.getElementById("group-errors"),
  emptyState: document.getElementById("empty-state"),
  editor: document.getElementById("editor"),
  selectedGroupName: document.getElementById("selected-group-name"),
  selectedGroupMeta: document.getElementById("selected-group-meta"),
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
  customPrompt: document.getElementById("custom-prompt"),
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
    custom_prompt: state.customPrompt,
  };
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
    remove.setAttribute("aria-label", `移除全局字段 ${label}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.customIdentityFields = state.customIdentityFields.filter(
        (item) => item !== label,
      );
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
    showNotice("最多添加 16 个全局自定义身份字段。", "warning");
    return;
  }
  state.customIdentityFields.push(label.slice(0, 32));
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
      label: "自定义昵称（可添加多个）",
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

function renderMembers({ scrollToFirst = false } = {}) {
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

  if (scrollToFirst) {
    requestAnimationFrame(() => {
      elements.members.querySelector(".member-card")?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  }
}

async function refreshMembers() {
  if (!state.selectedGroup) return;
  state.loadingMembers = true;
  elements.refreshMembers.disabled = true;
  showNotice("正在从 OneBot 刷新群成员信息…", "info");
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
    state.customPrompt = result.custom_prompt || "";
    elements.customPrompt.value = state.customPrompt;
    renderCustomIdentityFields();
    if (result.group_name) state.selectedGroup.group_name = result.group_name;
    elements.selectedGroupName.textContent = state.selectedGroup.group_name || `群 ${state.selectedGroup.group_id}`;
    renderMembers();
    elements.memberRefreshTime.textContent = `最近读取：${formatRefreshTime()}`;
    showNotice(
      `已刷新 ${state.members.length} 位群成员；平台昵称、群名片等资料已更新，已配置身份字段会按 QQ 号匹配保留。请保存本群设定以写入最新成员信息。`,
      "success",
    );
  } catch (error) {
    showNotice(error.message || "刷新群成员信息失败。", "error");
  } finally {
    state.loadingMembers = false;
    elements.refreshMembers.disabled = false;
  }
}

async function previewPrompt() {
  const payload = selectedPayload();
  if (!payload) return;
  elements.previewPrompt.disabled = true;
  try {
    const result = await bridge.apiPost("preview", payload);
    elements.promptOutput.textContent =
      result.prompt || "当前没有可注入的成员资料或自定义 Prompt。";
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
  try {
    const result = await bridge.apiPost("profiles", payload);
    elements.promptOutput.textContent =
      result.prompt || "当前没有可注入的成员资料或自定义 Prompt。";
    if (Array.isArray(result.custom_identity_fields)) {
      state.customIdentityFields = result.custom_identity_fields;
      renderCustomIdentityFields();
      renderMembers();
    }
    const selected = state.groups.find((group) => group.session_key === state.selectedGroup.session_key);
    if (selected) {
      selected.has_profile = Boolean(
        state.customPrompt.trim()
        || state.members.some((member) => hasConfiguredIdentity(member)),
      );
      selected.member_count = state.members.length;
    }
    renderGroupOptions();
    elements.groupSelect.value = state.selectedGroup.session_key;
    showNotice(
      `已保存 ${result.member_count} 位成员，已配置 ${result.configured_member_count || 0} 位；实际只注入最近 ${result.message_window_size || "配置的"} 条消息中的发言成员，以及消息中提到的已配置成员。${result.custom_prompt_enabled ? "已设置本群自定义 Prompt。" : "未设置本群自定义 Prompt。"}`,
      "success",
    );
  } catch (error) {
    showNotice(error.message || "保存设定失败。", "error");
  } finally {
    elements.saveProfile.disabled = false;
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
    });
    state.members = Array.isArray(result.members) ? result.members : [];
    state.customPrompt = "";
    state.memberSearch = "";
    state.memberPage = 1;
    state.showConfiguredOnly = false;
    elements.customPrompt.value = "";
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
      selected.has_profile = false;
      selected.member_count = state.members.length;
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
  state.customPrompt = "";
  state.memberSearch = "";
  state.memberPage = 1;
  state.showConfiguredOnly = false;
  elements.customPrompt.value = "";
  elements.memberSearch.value = "";
  elements.memberRefreshTime.textContent = "最近读取：尚未读取";
  updateConfiguredFilter();
  elements.promptOutput.textContent = "保存或预览后显示。";
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
  elements.refreshMembers.addEventListener("click", refreshMembers);
  elements.resetProfile.addEventListener("click", openResetConfirmation);
  elements.cancelReset.addEventListener("click", () => closeResetConfirmation());
  elements.confirmReset.addEventListener("click", performResetProfile);
  elements.resetConfirmation.addEventListener("click", (event) => {
    if (event.target === elements.resetConfirmation) closeResetConfirmation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.resetConfirmation.classList.contains("hidden")) {
      closeResetConfirmation();
    }
  });
  elements.previewPrompt.addEventListener("click", previewPrompt);
  elements.saveProfile.addEventListener("click", saveProfile);
  elements.customPrompt.addEventListener("input", () => {
    state.customPrompt = elements.customPrompt.value;
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
  await loadGroups();
}

init().catch((error) => showNotice(error.message || "页面初始化失败。", "error"));
