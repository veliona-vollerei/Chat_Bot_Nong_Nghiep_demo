/**
 * Chatbot Nông Nghiệp AI — Frontend JS (Nâng cấp)
 * Quản lý Xác thực (Auth), Admin Dashboard (Upload & Users), Lịch sử chat cá nhân hóa.
 */

const API_BASE = window.location.origin;
let isLoading = false;
let currentUser = JSON.parse(localStorage.getItem("chat_user") || "null");
let currentSessionId = localStorage.getItem("current_session_id") || `session_${Date.now()}`;
let conversationHistory = [];
let recognition = null;
let isRecording = false;

// ─── Init App ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  checkSystemStatus();
  setupInput();
  setupVoiceInput();
  setInterval(checkSystemStatus, 60000);
});

// ─── Authentication Logic ──────────────────────────────────
function initAuth() {
  const authModal = document.getElementById("authModal");
  if (!currentUser) {
    authModal.classList.remove("hidden");
    document.getElementById("userBadge").classList.add("hidden");
    document.getElementById("adminDashboardBtn").classList.add("hidden");
  } else {
    authModal.classList.add("hidden");
    updateUserUI();
    loadSessions();
    loadCurrentSessionMessages();
  }
}

function switchAuthMode(mode) {
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const authTitle = document.getElementById("authTitle");
  const authSub = document.getElementById("authSub");

  document.getElementById("loginError").classList.add("hidden");
  document.getElementById("registerError").classList.add("hidden");

  if (mode === "register") {
    loginForm.classList.add("hidden");
    registerForm.classList.remove("hidden");
    authTitle.textContent = "Tạo Tài Khoản Mới";
    authSub.textContent = "Đăng ký tài khoản để bắt đầu sử dụng trợ lý Nông Nghiệp AI";
  } else {
    registerForm.classList.add("hidden");
    loginForm.classList.remove("hidden");
    authTitle.textContent = "Đăng Nhập Hệ Thống";
    authSub.textContent = "Vui lòng đăng nhập để tiếp tục sử dụng Chatbot Nông Nghiệp";
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const usernameInput = document.getElementById("loginUsername").value.trim();
  const passwordInput = document.getElementById("loginPassword").value.trim();
  const errorBox = document.getElementById("loginError");
  errorBox.classList.add("hidden");

  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usernameInput, password: passwordInput })
    });

    const data = await res.json();
    if (!res.ok) {
      errorBox.textContent = data.detail || "Đăng nhập thất bại.";
      errorBox.classList.remove("hidden");
      return;
    }

    currentUser = data.user;
    localStorage.setItem("chat_user", JSON.stringify(currentUser));
    localStorage.setItem("user_token", data.token);

    document.getElementById("authModal").classList.add("hidden");
    updateUserUI();
    loadSessions();
    loadCurrentSessionMessages();
  } catch (err) {
    errorBox.textContent = "Lỗi kết nối máy chủ!";
    errorBox.classList.remove("hidden");
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const username = document.getElementById("regUsername").value.trim();
  const password = document.getElementById("regPassword").value.trim();
  const confirm = document.getElementById("regConfirmPassword").value.trim();
  const errorBox = document.getElementById("registerError");
  errorBox.classList.add("hidden");

  try {
    const res = await fetch(`${API_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, confirm_password: confirm })
    });

    const data = await res.json();
    if (!res.ok) {
      errorBox.textContent = data.detail || "Đăng ký thất bại.";
      errorBox.classList.remove("hidden");
      return;
    }

    alert("🎉 Đăng ký tài khoản thành công! Vui lòng đăng nhập.");
    switchAuthMode("login");
    document.getElementById("loginUsername").value = username;
  } catch (err) {
    errorBox.textContent = "Lỗi kết nối máy chủ!";
    errorBox.classList.remove("hidden");
  }
}

function handleLogout() {
  if (confirm("Bạn có chắc chắn muốn đăng xuất?")) {
    currentUser = null;
    localStorage.removeItem("chat_user");
    localStorage.removeItem("user_token");
    location.reload();
  }
}

function updateUserUI() {
  if (!currentUser) return;

  const badge = document.getElementById("userBadge");
  const usernameDisplay = document.getElementById("usernameDisplay");
  const roleTag = document.getElementById("userRoleTag");
  const adminBtn = document.getElementById("adminDashboardBtn");

  badge.classList.remove("hidden");
  usernameDisplay.textContent = currentUser.username;
  roleTag.textContent = currentUser.role;

  if (currentUser.role === "admin") {
    adminBtn.classList.remove("hidden");
  } else {
    adminBtn.classList.add("hidden");
  }
}

// ─── System Status ─────────────────────────────────────────
async function checkSystemStatus() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    const data = await res.json();
    const dot = document.querySelector(".status-dot");
    const text = document.querySelector(".status-text");

    if (data.status === "ok") {
      dot.className = "status-dot ok";
      text.textContent = `Sẵn sàng • ${data.chunks_loaded || 0} chunks`;
    } else {
      dot.className = "status-dot error";
      text.textContent = "Một số thành phần chưa kết nối";
    }
  } catch {
    const dot = document.querySelector(".status-dot");
    if (dot) dot.className = "status-dot error";
    const text = document.querySelector(".status-text");
    if (text) text.textContent = "Không kết nối được backend";
  }
}

// ─── Sessions Management (Personalized & Unlimited) ────────
async function loadSessions() {
  if (!currentUser) return;

  try {
    const res = await fetch(`${API_BASE}/api/sessions?username=${currentUser.username}`);
    if (!res.ok) return;
    const data = await res.json();
    const listContainer = document.getElementById("sessionsList");
    if (!listContainer) return;

    let sessions = data.sessions || [];

    // Nếu phiên hiện tại chưa nằm trong danh sách DB (vừa bấm Chat mới chưa gửi tin nhắn), chèn vào đầu
    const hasCurrent = sessions.some(s => s.session_id === currentSessionId);
    if (!hasCurrent) {
      sessions.unshift({
        session_id: currentSessionId,
        title: "Phiên trò chuyện mới",
        updated_at: new Date().toISOString()
      });
    }

    let html = "";
    sessions.forEach((s) => {
      const activeClass = s.session_id === currentSessionId ? "active" : "";
      const displayTitle = s.title && s.title !== "Trò chuyện mới" ? s.title : "Đoạn chat mới";
      html += `
        <div class="session-item ${activeClass}" onclick="switchSession('${s.session_id}')" data-id="${s.session_id}">
          <div class="session-left">
            <span class="session-icon">💬</span>
            <span class="session-name" title="${escapeHtml(displayTitle)}">${escapeHtml(displayTitle)}</span>
          </div>
          <button class="session-delete-btn" onclick="deleteSession(event, '${s.session_id}')" title="Xoá đoạn chat này">
            🗑️
          </button>
        </div>`;
    });
    listContainer.innerHTML = html;
  } catch (err) {
    console.error("Lỗi tải lịch sử phiên:", err);
  }
}

async function loadCurrentSessionMessages() {
  if (!currentUser) return;

  const container = document.getElementById("messagesContainer");
  try {
    const res = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/messages?username=${currentUser.username}`);
    if (!res.ok) return;
    const data = await res.json();

    container.innerHTML = "";
    conversationHistory = [];

    if (data.messages && data.messages.length > 0) {
      data.messages.forEach((msg) => {
        if (msg.sender === "user") {
          appendUserMessage(msg.content);
          conversationHistory.push({ role: "user", content: msg.content });
        } else {
          let metaData = {};
          try {
            metaData = typeof msg.metadata === "string" ? JSON.parse(msg.metadata) : msg.metadata || {};
          } catch (e) {}

          appendBotResponse({
            session_id: currentSessionId,
            answer: msg.content,
            source: metaData.source,
            is_partial_match: metaData.is_partial || false,
            layer_used: metaData.layer || "none",
            question_type: metaData.type
          });
          conversationHistory.push({ role: "assistant", content: msg.content });
        }
      });
    } else {
      renderWelcomeMessage();
    }
  } catch (err) {
    console.error("Lỗi tải tin nhắn phiên:", err);
  }
}

function renderWelcomeMessage() {
  const container = document.getElementById("messagesContainer");
  if (!container) return;
  container.innerHTML = `
    <div class="message bot-message">
        <div class="message-avatar">🌾</div>
        <div class="message-content">
            <div class="message-bubble">
                <p>Xin chào <strong>${escapeHtml(currentUser?.username || "Bạn")}</strong>! 👋</p>
                <p>Tôi là <strong>Nông Nghiệp AI</strong> — trợ lý tư vấn nông nghiệp thông minh. Tôi hỗ trợ tra cứu kỹ thuật và giải đáp thắc mắc về đa dạng nông sản:</p>
                <ul>
                    <li>🌱 <strong>Kỹ thuật canh tác & Phân bón</strong>: Lúa, cà phê, dưa hấu, sầu riêng, cây ăn quả, rau màu</li>
                    <li>💧 <strong>Quản lý nước & Tiết kiệm chi phí</strong>: Kỹ thuật tưới tiết kiệm, quản lý mùa vụ</li>
                    <li>🐛 <strong>Phòng trừ sâu bệnh</strong>: Nhận biết triệu chứng và biện pháp xử lý</li>
                    <li>📚 <strong>Tri thức nông nghiệp</strong>: Tra cứu từ tài liệu chính thống</li>
                </ul>
            </div>
            <div class="message-meta">Nông Nghiệp AI • Đã tạo đoạn chat mới</div>
        </div>
    </div>`;
}

function switchSession(sessionId) {
  if (currentSessionId === sessionId) return;
  currentSessionId = sessionId;
  localStorage.setItem("current_session_id", sessionId);
  loadSessions();
  loadCurrentSessionMessages();
}

function createNewSession() {
  currentSessionId = `session_${Date.now()}`;
  localStorage.setItem("current_session_id", currentSessionId);
  conversationHistory = [];
  loadSessions();
  renderWelcomeMessage();
}

async function deleteSession(e, sessionId) {
  e.stopPropagation();
  if (!confirm("Bạn có chắc chắn muốn xoá đoạn chat này khỏi lịch sử?")) return;

  try {
    const res = await fetch(`${API_BASE}/api/sessions/${sessionId}?username=${currentUser.username}`, {
      method: "DELETE"
    });
    if (res.ok) {
      if (currentSessionId === sessionId) {
        createNewSession();
      } else {
        loadSessions();
      }
    }
  } catch (err) {
    console.error("Lỗi xoá phiên:", err);
  }
}

// ─── Input Setup ───────────────────────────────────────────
function setupInput() {
  const input = document.getElementById("questionInput");
  const charCount = document.getElementById("charCount");

  input.addEventListener("input", () => {
    charCount.textContent = `${input.value.length}/500`;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 150) + "px";
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
}

// ─── Voice Recognition ─────────────────────────────────────
function setupVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    const voiceBtn = document.getElementById("voiceBtn");
    if (voiceBtn) voiceBtn.style.display = "none";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "vi-VN";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.onstart = () => {
    isRecording = true;
    document.getElementById("voiceBtn").classList.add("recording");
    document.getElementById("speechBanner").classList.remove("hidden");
  };

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    const input = document.getElementById("questionInput");
    input.value = transcript;
    document.getElementById("charCount").textContent = `${transcript.length}/500`;
  };

  recognition.onerror = () => stopVoiceInput();
  recognition.onend = () => stopVoiceInput();
}

function toggleVoiceInput() {
  if (!recognition) {
    alert("Trình duyệt không hỗ trợ thu âm bằng giọng nói.");
    return;
  }
  if (isRecording) {
    recognition.stop();
  } else {
    recognition.start();
  }
}

function stopVoiceInput() {
  if (recognition && isRecording) {
    recognition.stop();
  }
  isRecording = false;
  const voiceBtn = document.getElementById("voiceBtn");
  if (voiceBtn) voiceBtn.classList.remove("recording");
  const banner = document.getElementById("speechBanner");
  if (banner) banner.classList.add("hidden");
}

// ─── Text-to-Speech (TTS) ──────────────────────────────────
function speakText(btn, text) {
  if (!('speechSynthesis' in window)) {
    alert("Trình duyệt không hỗ trợ đọc văn bản.");
    return;
  }

  window.speechSynthesis.cancel();
  const cleanText = text.replace(/[*#_`]/g, "");
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "vi-VN";
  utterance.rate = 1.0;

  btn.textContent = "🔊 Đang đọc...";
  utterance.onend = () => { btn.textContent = "🔊 Đọc"; };
  utterance.onerror = () => { btn.textContent = "🔊 Đọc"; };

  window.speechSynthesis.speak(utterance);
}

// ─── Send Message ──────────────────────────────────────────
async function sendMessage() {
  if (isLoading || !currentUser) return;

  const input = document.getElementById("questionInput");
  const question = input.value.trim();
  if (!question) return;

  appendUserMessage(question);
  input.value = "";
  input.style.height = "auto";
  document.getElementById("charCount").textContent = "0/500";

  const typingId = showTyping();
  setLoading(true);

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        username: currentUser.username,
        question: question,
        conversation_history: conversationHistory.slice(-6),
      }),
    });

    if (res.status === 403) {
      alert("⚠️ Tài khoản của bạn đã bị chặn. Vui lòng liên hệ Admin.");
      location.reload();
      return;
    }

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    removeTyping(typingId);
    appendBotResponse(data);

    conversationHistory.push({ role: "user", content: question });
    conversationHistory.push({ role: "assistant", content: data.answer });

    loadSessions();
  } catch (err) {
    removeTyping(typingId);
    appendUserMessage(
      `❌ Lỗi kết nối backend: ${err.message}.`,
      "bot"
    );
  } finally {
    setLoading(false);
  }
}

// ─── Append Messages ───────────────────────────────────────
function appendUserMessage(text) {
  const container = document.getElementById("messagesContainer");
  const div = document.createElement("div");
  div.className = "message user-message";

  div.innerHTML = `
    <div class="message-avatar">👨‍🌾</div>
    <div class="message-content">
      <div class="message-bubble">${escapeHtml(text)}</div>
      <div class="message-meta">${escapeHtml(currentUser?.username || "Bạn")} • ${formatTime()}</div>
    </div>`;

  container.appendChild(div);
  scrollToBottom();
}

function appendBotResponse(data) {
  const container = document.getElementById("messagesContainer");
  const div = document.createElement("div");
  div.className = "message bot-message";

  let answerHtml = formatMarkdown(data.answer);

  let sourceBadge = "";
  if (data.source) {
    sourceBadge = `<div class="source-badge">📖 Nguồn: ${escapeHtml(data.source)}</div>`;
  }

  let warningBadge = "";
  if (data.is_partial_match && data.partial_match_warning) {
    warningBadge = `<div class="warning-badge">⚠️ ${escapeHtml(data.partial_match_warning)}</div>`;
  }

  let layerBadge = "";
  if (data.layer_used && data.layer_used !== "none") {
    layerBadge = `<div class="layer-badge">🔍 ${escapeHtml(data.layer_used)}</div>`;
  }

  const rawAnswerEscaped = escapeHtml(data.answer).replace(/'/g, "&#39;");

  // NÚT LIKE VÀ DISLIKE ĐÃ ĐƯỢC LOẠI BỎ HOÀN TOÀN THEO YÊU CẦU NÂNG CẤP
  div.innerHTML = `
    <div class="message-avatar">🌾</div>
    <div class="message-content">
      <div class="message-bubble">
        ${answerHtml}
        ${warningBadge}
      </div>
      ${sourceBadge}
      ${layerBadge}
      <div class="message-actions">
        <button class="action-btn" onclick="speakText(this, '${rawAnswerEscaped}')">🔊 Đọc</button>
        <button class="action-btn" onclick="copyText(this, '${rawAnswerEscaped}')">📋 Sao chép</button>
      </div>
      <div class="message-meta">Nông Nghiệp AI • ${formatTime()}</div>
    </div>`;

  container.appendChild(div);
  scrollToBottom();
}

function copyText(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    const originalText = btn.textContent;
    btn.textContent = "✅ Đã chép!";
    setTimeout(() => { btn.textContent = originalText; }, 2000);
  });
}

// ─── Admin Dashboard Logic ─────────────────────────────────
function toggleAdminDashboard() {
  const adminView = document.getElementById("adminDashboardView");
  const chatView = document.getElementById("chatMainView");

  if (adminView.classList.contains("hidden")) {
    adminView.classList.remove("hidden");
    chatView.classList.add("hidden");
    loadAdminUsers();
  } else {
    adminView.classList.add("hidden");
    chatView.classList.remove("hidden");
  }
}

function switchAdminTab(tab) {
  const tabUploadBtn = document.getElementById("tabUploadBtn");
  const tabUsersBtn = document.getElementById("tabUsersBtn");
  const uploadSection = document.getElementById("adminUploadSection");
  const usersSection = document.getElementById("adminUsersSection");

  if (tab === "upload") {
    tabUploadBtn.classList.add("active");
    tabUsersBtn.classList.remove("active");
    uploadSection.classList.remove("hidden");
    usersSection.classList.add("hidden");
  } else {
    tabUsersBtn.classList.add("active");
    tabUploadBtn.classList.remove("active");
    usersSection.classList.remove("hidden");
    uploadSection.classList.add("hidden");
    loadAdminUsers();
  }
}

async function handleAdminUpload(e) {
  e.preventDefault();
  const fileInput = document.getElementById("uploadFileInput");
  const file = fileInput.files[0];
  const submitBtn = document.getElementById("uploadSubmitBtn");
  const resultBox = document.getElementById("uploadResultBox");

  if (!file) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ Đang chạy marker-master pipeline...";
  resultBox.classList.remove("hidden");
  resultBox.innerHTML = `⏳ <strong>Đang xử lý file ${escapeHtml(file.name)}...</strong> Vui lòng chờ vài giây.`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/api/admin/upload-data?username=${currentUser.username}`, {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    if (!res.ok) {
      resultBox.innerHTML = `<span style="color:var(--accent-red)">❌ Lỗi: ${escapeHtml(data.detail || "Không thể upload file.")}</span>`;
      return;
    }

    resultBox.innerHTML = `
      <span style="color:var(--accent-green)">✅ <strong>Thành công!</strong></span><br>
      📄 Tài liệu: <strong>${escapeHtml(data.title)}</strong><br>
      📦 Tổng số Chunks tạo ra: <strong>${data.total_chunks}</strong><br>
      💾 Số Chunks đã nạp vào ChromaDB & PG: <strong>${data.stored_chunks}</strong>
    `;
    fileInput.value = "";
    checkSystemStatus();
  } catch (err) {
    resultBox.innerHTML = `<span style="color:var(--accent-red)">❌ Lỗi kết nối: ${err.message}</span>`;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "🚀 Chạy Pipeline & Cập Nhật Tri Thức";
  }
}

async function loadAdminUsers() {
  if (!currentUser || currentUser.role !== "admin") return;

  const tbody = document.getElementById("usersTableBody");
  tbody.innerHTML = `<tr><td colspan="6" class="text-center">Đang tải danh sách người dùng...</td></tr>`;

  try {
    const res = await fetch(`${API_BASE}/api/admin/users?username=${currentUser.username}`);
    const data = await res.json();

    if (!res.ok || !data.users) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-red">Lỗi tải người dùng!</td></tr>`;
      return;
    }

    let html = "";
    data.users.forEach((u) => {
      const isBlocked = u.is_blocked;
      const statusBadge = isBlocked 
        ? `<span class="badge-blocked">Đã bị chặn 🚫</span>`
        : `<span class="badge-active">Hoạt động ✅</span>`;

      const blockBtnText = isBlocked ? "Bỏ chặn" : "Chặn";
      const blockBtnClass = isBlocked ? "btn-unblock" : "btn-block";

      let actions = "";
      if (u.username !== "admin") {
        actions = `
          <button class="action-btn-sm ${blockBtnClass}" onclick="adminBlockUser(${u.user_id}, ${isBlocked})">${blockBtnText}</button>
          <button class="action-btn-sm btn-delete" onclick="adminDeleteUser(${u.user_id}, '${escapeHtml(u.username)}')">Xoá</button>
        `;
      } else {
        actions = `<span style="color:var(--text-muted);font-size:12px;">(Tài khoản Quản trị)</span>`;
      }

      html += `
        <tr>
          <td>${u.user_id}</td>
          <td><strong>${escapeHtml(u.username)}</strong></td>
          <td><span class="role-tag">${u.role}</span></td>
          <td>${statusBadge}</td>
          <td>${new Date(u.created_at).toLocaleDateString("vi-VN")}</td>
          <td>${actions}</td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-red">Lỗi kết nối máy chủ!</td></tr>`;
  }
}

async function adminBlockUser(userId, currentBlocked) {
  const newStatus = !currentBlocked;
  const actionText = newStatus ? "chặn" : "bỏ chặn";

  if (!confirm(`Bạn có chắc chắn muốn ${actionText} người dùng này?`)) return;

  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}/block?username=${currentUser.username}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_blocked: newStatus })
    });

    const data = await res.json();
    if (!res.ok) {
      alert("❌ " + (data.detail || "Thao tác thất bại."));
      return;
    }

    loadAdminUsers();
  } catch (err) {
    alert("❌ Lỗi kết nối máy chủ!");
  }
}

async function adminDeleteUser(userId, username) {
  if (!confirm(`⚠️ WARNING: Bạn có chắc chắn muốn XOÁ VĨNH VIỄN tài khoản '${username}'?`)) return;

  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}?username=${currentUser.username}`, {
      method: "DELETE"
    });

    const data = await res.json();
    if (!res.ok) {
      alert("❌ " + (data.detail || "Xoá tài khoản thất bại."));
      return;
    }

    loadAdminUsers();
  } catch (err) {
    alert("❌ Lỗi kết nối máy chủ!");
  }
}

// ─── Helpers ───────────────────────────────────────────────
function showTyping() {
  const container = document.getElementById("messagesContainer");
  const id = `typing-${Date.now()}`;
  const div = document.createElement("div");
  div.id = id;
  div.className = "message bot-message typing-indicator";
  div.innerHTML = `
    <div class="message-avatar">🌾</div>
    <div class="message-content">
      <div class="message-bubble">
        <div class="typing-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>`;
  container.appendChild(div);
  scrollToBottom();
  return id;
}

function removeTyping(id) {
  document.getElementById(id)?.remove();
}

function setLoading(state) {
  isLoading = state;
  document.getElementById("sendBtn").disabled = state;
}

function scrollToBottom() {
  const container = document.getElementById("messagesContainer");
  container.scrollTop = container.scrollHeight;
}

function formatTime() {
  return new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    return marked.parse(text);
  }
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^(.+)$/, "<p>$1</p>");
}
