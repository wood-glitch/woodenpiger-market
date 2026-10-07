(function () {
  "use strict";

  var storage = {
    get access() { return window.localStorage.getItem("wp_access_token"); },
    get refresh() { return window.localStorage.getItem("wp_refresh_token"); },
    set: function (access, refreshToken) {
      window.localStorage.setItem("wp_access_token", access);
      window.localStorage.setItem("wp_refresh_token", refreshToken);
    },
    clear: function () {
      window.localStorage.removeItem("wp_access_token");
      window.localStorage.removeItem("wp_refresh_token");
    }
  };

  var state = {
    user: null,
    checkedIn: false,
    categories: [],
    overview: null,
    worksCount: 0,
    worksNext: null,
    currentWorkId: null,
    query: { search: "", category: "all", tag: "", ordering: "-created_at" }
  };

  var elements = {
    adminLink: document.getElementById("admin-link"),
    profileAvatar: document.getElementById("profile-avatar"),
    profileAvatarFallback: document.getElementById("profile-avatar-fallback"),
    profileName: document.getElementById("profile-name"),
    profileBio: document.getElementById("profile-bio"),
    profileSkills: document.getElementById("profile-skills"),
    profileSettingsButton: document.getElementById("profile-settings-button"),
    profilePanel: document.getElementById("profile-panel"),
    closeProfilePanel: document.getElementById("close-profile-panel"),
    statWorkCount: document.getElementById("stat-work-count"),
    statSourceCount: document.getElementById("stat-source-count"),
    profileForm: document.getElementById("profile-form"),
    editorAvatarPreview: document.getElementById("editor-avatar-preview"),
    editorAvatarFallback: document.getElementById("editor-avatar-fallback"),
    avatarInput: document.getElementById("avatar-input"),
    profileUsernameInput: document.getElementById("profile-username-input"),
    profileBioInput: document.getElementById("profile-bio-input"),
    profileSkillsInput: document.getElementById("profile-skills-input"),
    profileError: document.getElementById("profile-error"),
    profileSaveButton: document.getElementById("profile-save-button"),
    userChip: document.getElementById("user-chip"),
    username: document.getElementById("current-username"),
    balance: document.getElementById("current-balance"),
    checkinButton: document.getElementById("checkin-button"),
    logoutButton: document.getElementById("logout-button"),
    authButton: document.getElementById("auth-button"),
    worksView: document.getElementById("works-view"),
    workDetailView: document.getElementById("work-detail-view"),
    walletView: document.getElementById("wallet-view"),
    resultCount: document.getElementById("result-count"),
    filters: document.getElementById("work-filters"),
    searchInput: document.getElementById("search-input"),
    tagInput: document.getElementById("tag-input"),
    categorySelect: document.getElementById("category-select"),
    categoryDropdown: document.getElementById("category-dropdown"),
    categoryDropdownLabel: document.getElementById("category-dropdown-label"),
    orderingSelect: document.getElementById("ordering-select"),
    orderingDropdown: document.getElementById("ordering-dropdown"),
    orderingDropdownLabel: document.getElementById("ordering-dropdown-label"),
    workGrid: document.getElementById("work-grid"),
    loadMore: document.getElementById("load-more-button"),
    backToWorks: document.getElementById("back-to-works"),
    workCategory: document.getElementById("work-category"),
    workTitle: document.getElementById("work-title"),
    workAuthor: document.getElementById("work-author"),
    workCreatedAt: document.getElementById("work-created-at"),
    workFileCount: document.getElementById("work-file-count"),
    workPrice: document.getElementById("work-price"),
    workSummary: document.getElementById("work-summary"),
    workContent: document.getElementById("work-content"),
    workGallery: document.getElementById("work-gallery"),
    workTags: document.getElementById("work-tags"),
    workVersions: document.getElementById("work-versions"),
    workAuthorAvatar: document.getElementById("work-author-avatar"),
    workAuthorFallback: document.getElementById("work-author-fallback"),
    workAuthorName: document.getElementById("work-author-name"),
    workAuthorBio: document.getElementById("work-author-bio"),
    workAuthorSkills: document.getElementById("work-author-skills"),
    unlockButton: document.getElementById("unlock-button"),
    unlockNote: document.getElementById("unlock-note"),
    downloadSourceZip: document.getElementById("download-source-zip"),
    sourceTree: document.getElementById("source-tree"),
    sourceFilePath: document.getElementById("source-file-path"),
    sourceDownload: document.getElementById("source-download"),
    sourceContent: document.getElementById("source-file-content"),
    walletLogin: document.getElementById("wallet-login"),
    walletContent: document.getElementById("wallet-content"),
    walletLoginButton: document.getElementById("wallet-login-button"),
    walletBalance: document.getElementById("wallet-balance"),
    transactionList: document.getElementById("transaction-list"),
    authModal: document.getElementById("auth-modal"),
    authTitle: document.getElementById("auth-title"),
    loginTab: document.getElementById("login-tab"),
    registerTab: document.getElementById("register-tab"),
    closeAuthModal: document.getElementById("close-auth-modal"),
    authForm: document.getElementById("auth-form"),
    authError: document.getElementById("auth-error"),
    authSubmit: document.getElementById("auth-submit"),
    toast: document.getElementById("toast")
  };

  var authMode = "login";
  var toastTimer = null;
  var workCardObserver = "IntersectionObserver" in window
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          workCardObserver.unobserve(entry.target);
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -36px 0px" })
    : null;

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function formatError(data) {
    if (!data) return "请求失败，请稍后再试";
    var detail = data.detail || data.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.join("，");
    if (detail && typeof detail === "object") {
      return Object.keys(detail).map(function (key) {
        var value = detail[key];
        if (Array.isArray(value)) value = value.join("，");
        return key + ": " + value;
      }).join("；");
    }
    return "请求失败，请检查输入后重试";
  }

  async function refreshAccessToken() {
    var refreshToken = storage.refresh;
    if (!refreshToken) return false;

    var response = await fetch("/api/auth/token/refresh/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: refreshToken })
    });
    if (!response.ok) return false;

    var data = await response.json();
    storage.set(data.access, refreshToken);
    return true;
  }

  async function api(path, options, allowRefresh) {
    if (allowRefresh === undefined) allowRefresh = true;
    options = options || {};
    var headers = new Headers(options.headers || {});
    if (options.body && typeof options.body === "string") {
      headers.set("Content-Type", "application/json");
    }
    if (storage.access) headers.set("Authorization", "Bearer " + storage.access);

    var response = await fetch(path, Object.assign({}, options, { headers: headers }));
    if (response.status === 401 && allowRefresh && storage.refresh) {
      var refreshed = await refreshAccessToken();
      if (refreshed) return api(path, options, false);
    }

    if (response.status === 204) return null;
    var data = null;
    if (response.headers.get("Content-Type")) {
      data = await response.json().catch(function () { return null; });
    }
    if (!response.ok) {
      var error = new Error(formatError(data));
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function showToast(message) {
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("visible");
    toastTimer = window.setTimeout(function () {
      elements.toast.classList.remove("visible");
    }, 2800);
  }

  function formatDate(value) {
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return date.getFullYear() + "-" + month + "-" + day;
  }

  function categoryMap() {
    return state.categories.reduce(function (mapping, category) {
      mapping[category.id] = category.name;
      return mapping;
    }, {});
  }

  function setAvatar(frameImage, fallback, profile) {
    var name = profile && profile.username ? profile.username : "W";
    frameImage.alt = name + " 的头像";
    if (profile && profile.avatar) {
      frameImage.src = profile.avatar;
      frameImage.hidden = false;
      fallback.textContent = "";
    } else {
      frameImage.hidden = true;
      frameImage.removeAttribute("src");
      fallback.textContent = name.charAt(0).toUpperCase();
    }
  }

  function renderTags(container, tags) {
    container.textContent = "";
    (tags || []).forEach(function (tag) {
      container.appendChild(element("li", "", tag));
    });
  }

  function renderWorkVersions(versions) {
    elements.workVersions.textContent = "";
    if (!versions || !versions.length) {
      var emptyItem = element("li", "version-item");
      emptyItem.appendChild(element("span", "version-name", "暂无版本更新"));
      elements.workVersions.appendChild(emptyItem);
      return;
    }

    versions.forEach(function (version) {
      var item = element("li", "version-item");
      var heading = element("div", "version-heading");
      heading.appendChild(element("span", "version-name", version.version));
      heading.appendChild(element("span", "version-date", formatDate(version.released_at)));
      item.appendChild(heading);
      if (version.changelog) {
        item.appendChild(element("p", "version-changelog", version.changelog));
      }
      elements.workVersions.appendChild(item);
    });
  }

  function renderBio(container, bio) {
    var value = String(bio || "");
    container.textContent = "";

    if (!value) {
      container.textContent = "这位作者还没有填写介绍。";
      return;
    }

    var pattern = /(?:https?:\/\/|www\.|github\.com\/)[^\s<>"')\]]+/gi;
    var lastIndex = 0;
    var match;

    function appendText(text) {
      if (text) container.appendChild(document.createTextNode(text));
    }

    while ((match = pattern.exec(value)) !== null) {
      var token = match[0].replace(/[.,;:!?]+$/, "");
      if (!token) continue;

      var href = /^https?:\/\//i.test(token) ? token : "https://" + token;
      var url;
      try {
        url = new URL(href);
      } catch (error) {
        continue;
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") continue;

      appendText(value.slice(lastIndex, match.index));
      var link = element("a", "bio-link", token);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      container.appendChild(link);
      lastIndex = match.index + token.length;
      pattern.lastIndex = lastIndex;
    }

    appendText(value.slice(lastIndex));
  }

  function openProfilePanel() {
    if (!state.user) return;
    elements.profilePanel.hidden = false;
    elements.profileUsernameInput.focus();
  }

  function closeProfilePanel() {
    elements.profilePanel.hidden = true;
  }

  function syncDropdown(details, label, value) {
    var selected = null;
    details.querySelectorAll(".glass-dropdown-option").forEach(function (option) {
      var isSelected = option.dataset.value === String(value);
      option.setAttribute("aria-selected", String(isSelected));
      option.classList.toggle("selected", isSelected);
      if (isSelected) selected = option;
    });
    label.textContent = selected ? selected.textContent : "请选择";
  }

  function renderCategoryDropdown() {
    var menu = elements.categoryDropdown.querySelector(".glass-dropdown-menu");
    menu.textContent = "";
    [{ id: "all", name: "全部分类" }].concat(state.categories).forEach(function (category) {
      var option = element("button", "glass-dropdown-option", category.name);
      option.type = "button";
      option.dataset.value = String(category.id);
      option.setAttribute("role", "option");
      menu.appendChild(option);
    });
    syncDropdown(
      elements.categoryDropdown,
      elements.categoryDropdownLabel,
      elements.categorySelect.value
    );
  }

  function closeDropdowns() {
    document.querySelectorAll("details.glass-dropdown[open]").forEach(function (dropdown) {
      dropdown.open = false;
      dropdown.querySelector("summary").setAttribute("aria-expanded", "false");
    });
  }

  function bindDropdown(details, label, input) {
    var summary = details.querySelector("summary");
    summary.setAttribute("aria-expanded", "false");

    details.addEventListener("toggle", function () {
      summary.setAttribute("aria-expanded", String(details.open));
      if (!details.open) return;
      document.querySelectorAll("details.glass-dropdown[open]").forEach(function (other) {
        if (other === details) return;
        other.open = false;
        other.querySelector("summary").setAttribute("aria-expanded", "false");
      });
    });

    details.querySelector(".glass-dropdown-menu").addEventListener("click", function (event) {
      var option = event.target.closest(".glass-dropdown-option");
      if (!option) return;
      input.value = option.dataset.value;
      syncDropdown(details, label, input.value);
      details.open = false;
    });
  }

  async function loadOverview() {
    var overview = await api("/api/site/overview/");
    state.overview = overview;

    if (overview.profile) {
      setAvatar(elements.profileAvatar, elements.profileAvatarFallback, overview.profile);
      elements.profileName.textContent = overview.profile.username;
      renderBio(elements.profileBio, overview.profile.bio);
      renderTags(elements.profileSkills, overview.profile.skills);
    }
    elements.statWorkCount.textContent = overview.work_count;
    elements.statSourceCount.textContent = overview.source_file_count;
  }

  async function loadCategories() {
    var data = await api("/api/categories/");
    state.categories = data.results || data || [];
    elements.categorySelect.textContent = "";
    var allOption = element("option", "", "全部分类");
    allOption.value = "all";
    elements.categorySelect.appendChild(allOption);
    state.categories.forEach(function (category) {
      var option = element("option", "", category.name);
      option.value = String(category.id);
      elements.categorySelect.appendChild(option);
    });
    renderCategoryDropdown();
  }

  function workParams(page) {
    var params = new URLSearchParams();
    if (state.query.search) params.set("search", state.query.search);
    if (state.query.category !== "all") params.set("category", state.query.category);
    if (state.query.tag) params.set("tag", state.query.tag.trim());
    params.set("ordering", state.query.ordering);
    params.set("page", String(page));
    return params.toString();
  }

  async function loadWorks(page) {
    if (page === 1) {
      elements.workGrid.textContent = "";
      elements.workGrid.appendChild(element("article", "empty-state", "正在加载作品..."));
    }

    try {
      var data = await api("/api/works/?" + workParams(page));
      var results = data.results || [];
      state.worksCount = data.count || results.length;
      state.worksNext = data.next || null;
      if (page === 1) elements.workGrid.textContent = "";

      if (!results.length && page === 1) {
        elements.workGrid.appendChild(element("article", "empty-state", "还没有已发布作品"));
      } else {
        var categories = categoryMap();
        results.forEach(function (work, index) {
          elements.workGrid.appendChild(
            createWorkCard(work, categories, page === 1 && index === 0)
          );
        });
      }

      elements.resultCount.textContent = "共 " + state.worksCount + " 个作品";
      elements.loadMore.hidden = !state.worksNext;
    } catch (error) {
      if (page === 1) {
        elements.workGrid.textContent = "";
        elements.workGrid.appendChild(element("article", "empty-state", error.message));
      } else {
        showToast(error.message);
      }
    }
  }

  function createWorkCard(work, categories, featured) {
    var card = element("article", "work-card");
    var hasCover = Boolean(work.images && work.images.length);
    if (featured && hasCover) card.classList.add("featured");
    if (hasCover) {
      var media = element("div", "work-media");
      var image = element("img");
      image.src = work.images[0].image;
      image.alt = work.title + " 封面";
      media.appendChild(image);
      card.appendChild(media);
    }

    var body = element("div", "work-card-body");
    body.appendChild(element("h2", "", work.title));
    body.appendChild(element("p", "work-card-summary", work.summary || "暂无简介"));
    var tags = element("ul", "tag-list");
    renderTags(tags, work.tags);
    body.appendChild(tags);

    var footer = element("div", "work-card-footer");
    var categoryText = work.category ? categories[work.category] || "分类" : "未分类";
    var author = work.author || {};
    var authorRow = element("div", "author-row");
    if (author.avatar) {
      var avatar = element("img");
      avatar.src = author.avatar;
      avatar.alt = author.username + " 的头像";
      authorRow.appendChild(avatar);
    } else {
      var fallback = element("span", "author-fallback");
      fallback.textContent = (author.username || "W").charAt(0).toUpperCase();
      authorRow.appendChild(fallback);
    }
    authorRow.appendChild(element("span", "", categoryText + " · " + (author.username || "未知作者")));
    footer.appendChild(authorRow);
    footer.appendChild(element("span", "price", work.cost_piger === 0 ? "免费" : work.cost_piger + " piger"));
    body.appendChild(footer);

    var button = element("button", "glass-button wide", "查看详情");
    button.type = "button";
    button.addEventListener("click", function () {
      window.location.hash = "#/works/" + work.id;
    });
    body.appendChild(button);
    card.appendChild(body);
    if (workCardObserver) workCardObserver.observe(card);
    else card.classList.add("is-visible");
    return card;
  }

  function clearWorkDetail() {
    elements.workTitle.textContent = "";
    elements.workCategory.textContent = "";
    elements.workAuthor.textContent = "";
    elements.workCreatedAt.textContent = "";
    elements.workFileCount.textContent = "";
    elements.workPrice.textContent = "";
    renderTags(elements.workTags, []);
    renderWorkVersions([]);
    elements.downloadSourceZip.hidden = true;
    elements.downloadSourceZip.removeAttribute("href");
    setAvatar(elements.workAuthorAvatar, elements.workAuthorFallback, null);
    elements.workAuthorName.textContent = "";
    renderBio(elements.workAuthorBio, "");
    renderTags(elements.workAuthorSkills, []);
    elements.workSummary.textContent = "";
    elements.workContent.textContent = "";
    elements.workGallery.textContent = "";
    elements.unlockNote.textContent = "";
    elements.sourceTree.textContent = "";
    elements.sourceFilePath.textContent = "选择左侧文件";
    elements.sourceContent.textContent = "";
    elements.sourceDownload.hidden = true;
    elements.sourceDownload.removeAttribute("href");
  }

  async function showWork(workId) {
    state.currentWorkId = workId;
    clearWorkDetail();
    elements.workTitle.textContent = "正在加载...";
    elements.workSummary.textContent = "";

    try {
      var work = await api("/api/works/" + workId + "/");
      var categories = categoryMap();
      elements.workCategory.textContent = work.category ? categories[work.category] || "作品" : "作品";
      elements.workTitle.textContent = work.title;
      var author = work.author || {};
      elements.workAuthor.textContent = "作者：" + (author.username || "未知");
      elements.workCreatedAt.textContent = "发布：" + formatDate(work.created_at);
      elements.workFileCount.textContent = work.source_file_count + " files";
      elements.workPrice.textContent = work.cost_piger === 0 ? "免费" : work.cost_piger + " piger";
    renderTags(elements.workTags, work.tags);
    renderWorkVersions(work.versions);
    elements.downloadSourceZip.href = work.source_download_url || "#";
    elements.downloadSourceZip.hidden = !(
      work.can_view_source &&
      work.source_file_count > 0 &&
      work.source_download_url
    );
    setAvatar(elements.workAuthorAvatar, elements.workAuthorFallback, author);
    elements.workAuthorName.textContent = author.username || "未知作者";
    renderBio(elements.workAuthorBio, author.bio);
      renderTags(elements.workAuthorSkills, author.skills);
      elements.workSummary.textContent = work.summary || "暂无简介";
      elements.workContent.textContent = work.content || (
        work.can_view_source ? "暂无详细说明" : "解锁后查看详细说明与源码。"
      );

      (work.images || []).forEach(function (imageData) {
        var image = element("img");
        image.src = imageData.image;
        image.alt = work.title + " 截图";
        elements.workGallery.appendChild(image);
      });

      renderUnlockState(work);
      renderSourceTree(work.source_tree || []);
    } catch (error) {
      clearWorkDetail();
      elements.workTitle.textContent = "作品加载失败";
      elements.workSummary.textContent = error.message;
    }
  }

  function renderUnlockState(work) {
    elements.unlockButton.disabled = false;
    elements.unlockNote.textContent = work.can_view_source ? "已拥有访问权限" : "解锁一次，永久有效";
    if (work.can_view_source) {
      elements.sourceFilePath.textContent = "选择左侧文件";
      elements.sourceContent.textContent = "";
    } else {
      elements.sourceFilePath.textContent = "源码未解锁";
      elements.sourceContent.textContent = "使用 piger 解锁后可阅读和下载源码。";
    }

    if (work.can_view_source) {
      elements.unlockButton.textContent = "已解锁";
      elements.unlockButton.disabled = true;
    } else if (!state.user) {
      elements.unlockButton.textContent = "登录后解锁";
    } else {
      elements.unlockButton.textContent = "解锁 · " + work.cost_piger + " piger";
    }
  }

  function renderSourceTree(nodes) {
    elements.sourceTree.textContent = "";
    nodes.forEach(function (node) {
      appendSourceNode(elements.sourceTree, node);
    });
    if (!nodes.length) {
      elements.sourceTree.appendChild(element("li", "", "暂无源码文件"));
    }
  }

  function appendSourceNode(parent, node) {
    var item = element("li", node.type === "directory" ? "tree-directory" : "tree-file");
    var button = element("button", "", node.name);
    button.type = "button";
    item.appendChild(button);

    if (node.type === "directory") {
      var children = element("ul", "tree-children");
      children.hidden = true;
      button.addEventListener("click", function () {
        children.hidden = !children.hidden;
      });
      node.children.forEach(function (child) {
        appendSourceNode(children, child);
      });
      item.appendChild(children);
    } else {
      button.addEventListener("click", function () {
        document.querySelectorAll(".source-tree button.active").forEach(function (active) {
          active.classList.remove("active");
        });
        button.classList.add("active");
        openSourceFile(node);
      });
    }
    parent.appendChild(item);
  }

  async function openSourceFile(node) {
    elements.sourceFilePath.textContent = node.path;
    elements.sourceContent.textContent = "正在读取文件...";
    elements.sourceDownload.hidden = true;
    elements.sourceDownload.removeAttribute("href");

    try {
      var data = await api("/api/works/" + state.currentWorkId + "/source-files/" + node.file_id + "/");
      elements.sourceContent.textContent = data.is_text ? data.content : "此文件为二进制格式，请下载后查看。";
      if (data.download_url) {
        elements.sourceDownload.href = data.download_url;
        elements.sourceDownload.hidden = false;
      }
    } catch (error) {
      elements.sourceContent.textContent = error.message;
    }
  }

  async function unlockCurrentWork() {
    if (!state.user) {
      openAuthModal("login");
      return;
    }

    elements.unlockButton.disabled = true;
    try {
      await api("/api/works/" + state.currentWorkId + "/unlock/", { method: "POST" });
      await loadCurrentUser();
      await showWork(state.currentWorkId);
      showToast("作品已解锁");
    } catch (error) {
      elements.unlockButton.disabled = false;
      showToast(error.message);
    }
  }

  async function loadWallet() {
    if (!storage.access) {
      elements.walletLogin.hidden = false;
      elements.walletContent.hidden = true;
      return;
    }

    elements.walletLogin.hidden = true;
    elements.walletContent.hidden = false;
    elements.walletBalance.textContent = "...";
    elements.transactionList.textContent = "";

    try {
      var wallet = await api("/api/wallet/");
      elements.walletBalance.textContent = wallet.piger_balance;
      if (!wallet.transactions.length) {
        elements.transactionList.appendChild(element("div", "empty-state", "暂无流水记录"));
        return;
      }
      wallet.transactions.forEach(createTransactionRow);
    } catch (error) {
      elements.walletBalance.textContent = "0";
      elements.transactionList.appendChild(element("div", "empty-state", error.message));
    }
  }

  function createTransactionRow(transaction) {
    var row = element("div", "transaction-row");
    var reason = element("div", "transaction-reason", transactionReason(transaction.reason));
    var work = element("div", "transaction-work", transaction.work || "无关联作品");
    var amountClass = transaction.amount >= 0 ? "positive" : "negative";
    var amountText = (transaction.amount >= 0 ? "+" : "") + transaction.amount;
    work.appendChild(element("span", "amount " + amountClass, amountText + " piger"));
    var date = element("div", "transaction-date", formatDate(transaction.created_at));
    row.appendChild(reason);
    row.appendChild(work);
    row.appendChild(date);
    elements.transactionList.appendChild(row);
  }

  function transactionReason(reason) {
    var labels = {
      register: "注册赠送",
      checkin: "每日签到",
      unlock: "解锁作品",
      admin_grant: "管理员调整"
    };
    return labels[reason] || reason;
  }

  async function loadCurrentUser() {
    if (!storage.access) {
      state.user = null;
      renderAuthState();
      return;
    }

    try {
      state.user = await api("/api/auth/me/");
      renderAuthState();
      await loadCheckinStatus();
    } catch (error) {
      if (error.status === 401) {
        storage.clear();
        state.user = null;
        renderAuthState();
      }
    }
  }

  async function loadCheckinStatus() {
    if (!state.user) return;
    try {
      var status = await api("/api/checkins/status/");
      state.checkedIn = status.has_checked_in;
      state.user.piger_balance = status.piger_balance;
      renderAuthState();
    } catch (error) {
      showToast(error.message);
    }
  }

  function renderAuthState() {
    var authenticated = Boolean(state.user);
    elements.userChip.hidden = !authenticated;
    elements.checkinButton.hidden = !authenticated;
    elements.logoutButton.hidden = !authenticated;
    elements.authButton.hidden = authenticated;
    elements.profileForm.hidden = !authenticated;
    elements.profileSettingsButton.hidden = !authenticated;
    elements.adminLink.hidden = !(authenticated && state.user && state.user.is_staff);
    if (!authenticated) closeProfilePanel();
    if (authenticated) {
      elements.username.textContent = state.user.username;
      elements.balance.textContent = state.user.piger_balance;
      elements.checkinButton.textContent = state.checkedIn ? "已签到" : "签到 +1";
      elements.checkinButton.disabled = state.checkedIn;
      setAvatar(elements.editorAvatarPreview, elements.editorAvatarFallback, state.user);
      elements.profileUsernameInput.value = state.user.username || "";
      elements.profileBioInput.value = state.user.bio || "";
      elements.profileSkillsInput.value = (state.user.skills || []).join(", ");
      elements.profileError.textContent = "";
    } else {
      setAvatar(elements.editorAvatarPreview, elements.editorAvatarFallback, null);
      elements.profileUsernameInput.value = "";
      elements.profileBioInput.value = "";
      elements.profileSkillsInput.value = "";
      elements.profileError.textContent = "";
    }
  }

  async function submitProfile(event) {
    event.preventDefault();
    elements.profileSaveButton.disabled = true;
    elements.profileError.textContent = "";

    var formData = new FormData(elements.profileForm);
    if (elements.avatarInput.files.length) {
      formData.set("avatar", elements.avatarInput.files[0]);
    }

    try {
      await api("/api/auth/me/profile/", {
        method: "PATCH",
        body: formData
      });
      await loadCurrentUser();
      elements.avatarInput.value = "";
      if (elements.editorAvatarPreview.dataset.objectUrl) {
        window.URL.revokeObjectURL(elements.editorAvatarPreview.dataset.objectUrl);
        delete elements.editorAvatarPreview.dataset.objectUrl;
      }
      if (state.overview && state.overview.profile && state.user &&
          state.overview.profile.id === state.user.id) {
        await loadOverview();
      }
      showToast("个人资料已保存");
    } catch (error) {
      elements.profileError.textContent = error.message;
    } finally {
      elements.profileSaveButton.disabled = false;
    }
  }

  function setAuthMode(mode) {
    authMode = mode;
    var isLogin = mode === "login";
    elements.authTitle.textContent = isLogin ? "登录" : "注册";
    elements.authSubmit.textContent = isLogin ? "登录" : "注册并获得 5 piger";
    elements.loginTab.classList.toggle("active", isLogin);
    elements.registerTab.classList.toggle("active", !isLogin);
    elements.loginTab.setAttribute("aria-selected", String(isLogin));
    elements.registerTab.setAttribute("aria-selected", String(!isLogin));
    elements.authForm.elements.password.autocomplete = isLogin ? "current-password" : "new-password";
    elements.authError.textContent = "";
  }

  function openAuthModal(mode) {
    setAuthMode(mode);
    elements.authModal.hidden = false;
    elements.authForm.elements.username.focus();
  }

  function closeAuthModal() {
    elements.authModal.hidden = true;
    elements.authForm.reset();
    elements.authError.textContent = "";
  }

  async function submitAuth(event) {
    event.preventDefault();
    elements.authSubmit.disabled = true;
    elements.authError.textContent = "";

    var formData = new FormData(elements.authForm);
    var payload = {
      username: String(formData.get("username") || "").trim(),
      password: String(formData.get("password") || "")
    };

    try {
      if (authMode === "register") {
        await api("/api/auth/register/", {
          method: "POST",
          body: JSON.stringify(payload)
        });
      }
      var token = await api("/api/auth/token/", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      storage.set(token.access, token.refresh);
      closeAuthModal();
      await loadCurrentUser();
      showToast(authMode === "register" ? "注册成功，已赠送 5 piger" : "登录成功");
      if (!elements.walletView.hidden) await loadWallet();
    } catch (error) {
      elements.authError.textContent = error.message;
    } finally {
      elements.authSubmit.disabled = false;
    }
  }

  async function checkIn() {
    elements.checkinButton.disabled = true;
    try {
      state.user = await api("/api/checkins/", { method: "POST" });
      state.checkedIn = true;
      renderAuthState();
      showToast("签到成功，获得 1 piger");
    } catch (error) {
      if (error.status === 409) {
        state.checkedIn = true;
        renderAuthState();
      }
      showToast(error.message);
    }
  }

  function logout() {
    storage.clear();
    state.user = null;
    state.checkedIn = false;
    renderAuthState();
    window.location.hash = "#/works";
    showToast("已退出登录");
  }

  function setActiveView(view) {
    elements.worksView.hidden = view !== "works";
    elements.workDetailView.hidden = view !== "work";
    elements.walletView.hidden = view !== "wallet";

    document.querySelectorAll(".main-nav a").forEach(function (link) {
      var current = link.dataset.nav === view || (view === "work" && link.dataset.nav === "works");
      if (current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  async function route() {
    var hash = window.location.hash || "#/works";
    var workMatch = hash.match(/^#\/works\/(\d+)\/?$/);

    if (workMatch) {
      setActiveView("work");
      await showWork(workMatch[1]);
      return;
    }

    if (hash === "#/wallet") {
      setActiveView("wallet");
      await loadWallet();
      return;
    }

    setActiveView("works");
  }

  function resetFilters() {
    state.query = { search: "", category: "all", tag: "", ordering: "-created_at" };
    elements.searchInput.value = "";
    elements.tagInput.value = "";
    elements.categorySelect.value = "all";
    elements.orderingSelect.value = "-created_at";
    syncDropdown(
      elements.categoryDropdown,
      elements.categoryDropdownLabel,
      elements.categorySelect.value
    );
    syncDropdown(
      elements.orderingDropdown,
      elements.orderingDropdownLabel,
      elements.orderingSelect.value
    );
    loadWorks(1);
  }

  function bindEvents() {
    window.addEventListener("hashchange", route);

    elements.filters.addEventListener("submit", function (event) {
      event.preventDefault();
      state.query.search = elements.searchInput.value.trim();
      state.query.category = elements.categorySelect.value;
      state.query.tag = elements.tagInput.value.trim();
      state.query.ordering = elements.orderingSelect.value;
      loadWorks(1);
    });

    elements.filters.addEventListener("reset", function () {
      window.setTimeout(resetFilters, 0);
    });

    bindDropdown(
      elements.categoryDropdown,
      elements.categoryDropdownLabel,
      elements.categorySelect
    );
    bindDropdown(
      elements.orderingDropdown,
      elements.orderingDropdownLabel,
      elements.orderingSelect
    );
    document.addEventListener("click", function (event) {
      if (event.target.closest("details.glass-dropdown")) return;
      closeDropdowns();
    });

    elements.loadMore.addEventListener("click", function () {
      if (!state.worksNext) return;
      var page = new URL(state.worksNext, window.location.origin).searchParams.get("page");
      if (page) loadWorks(Number(page));
    });

    elements.backToWorks.addEventListener("click", function () {
      window.location.hash = "#/works";
    });
    elements.unlockButton.addEventListener("click", unlockCurrentWork);
    elements.checkinButton.addEventListener("click", checkIn);
    elements.logoutButton.addEventListener("click", logout);
    elements.profileSettingsButton.addEventListener("click", function () {
      if (elements.profilePanel.hidden) openProfilePanel();
      else closeProfilePanel();
    });
    elements.closeProfilePanel.addEventListener("click", closeProfilePanel);
    document.addEventListener("click", function (event) {
      if (elements.profilePanel.hidden) return;
      if (elements.profilePanel.contains(event.target)) return;
      if (elements.profileSettingsButton.contains(event.target)) return;
      closeProfilePanel();
    });
    elements.authButton.addEventListener("click", function () { openAuthModal("login"); });
    elements.walletLoginButton.addEventListener("click", function () { openAuthModal("login"); });
    elements.loginTab.addEventListener("click", function () { setAuthMode("login"); });
    elements.registerTab.addEventListener("click", function () { setAuthMode("register"); });
    elements.closeAuthModal.addEventListener("click", closeAuthModal);
    elements.authModal.addEventListener("click", function (event) {
      if (event.target === elements.authModal) closeAuthModal();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      closeDropdowns();
      if (!elements.authModal.hidden) closeAuthModal();
      else if (!elements.profilePanel.hidden) closeProfilePanel();
    });
    elements.authForm.addEventListener("submit", submitAuth);
    elements.profileForm.addEventListener("submit", submitProfile);
    elements.avatarInput.addEventListener("change", function () {
      if (!elements.avatarInput.files.length) return;
      var file = elements.avatarInput.files[0];
      if (elements.editorAvatarPreview.dataset.objectUrl) {
        window.URL.revokeObjectURL(elements.editorAvatarPreview.dataset.objectUrl);
      }
      var objectUrl = window.URL.createObjectURL(file);
      elements.editorAvatarPreview.src = objectUrl;
      elements.editorAvatarPreview.hidden = false;
      elements.editorAvatarPreview.dataset.objectUrl = objectUrl;
      elements.editorAvatarFallback.textContent = "";
    });
  }

  async function initialize() {
    bindEvents();
    renderAuthState();
    await loadCurrentUser();
    try {
      await loadCategories();
      await loadOverview();
    } catch (error) {
      showToast(error.message);
    }
    await route();
    if (!elements.worksView.hidden) await loadWorks(1);
  }

  initialize().catch(function (error) {
    showToast(error.message || "初始化失败");
  });
})();

(function initSidebarWidgets() {
  function updateTime() {
    var timeDisplay = document.getElementById('current-time-display');
    var dateDisplay = document.getElementById('current-date-display');
    if (!timeDisplay || !dateDisplay) return;
    
    var now = new Date();
    var hours = String(now.getHours()).padStart(2, '0');
    var minutes = String(now.getMinutes()).padStart(2, '0');
    var seconds = String(now.getSeconds()).padStart(2, '0');
    timeDisplay.textContent = hours + ':' + minutes + ':' + seconds;
    
    var year = now.getFullYear();
    var month = String(now.getMonth() + 1).padStart(2, '0');
    var date = String(now.getDate()).padStart(2, '0');
    var days = ['日', '一', '二', '三', '四', '五', '六'];
    var day = days[now.getDay()];
    
    dateDisplay.textContent = year + '年' + month + '月' + date + '日 星期' + day;
  }
  
  updateTime();
  setInterval(updateTime, 1000);
})();
