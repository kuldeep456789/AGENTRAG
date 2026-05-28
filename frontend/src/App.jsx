import { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { getHealth, ingestDocument, login, queryAgent, analyzeImage, seedWebKnowledge, listWebKnowledge, getWebKnowledgePage, deleteWebKnowledgePage } from "./api";
import { formatPageTimestamp, formatStatNumber, getDisplayHost, pageDetailToMarkdown } from "./webPageFormat";
import { renderMarkdown } from "./markdownRender";

const starterPrompts = [
  "Summarize the uploaded contract and highlight risks.",
  "Explain the multilingual RAG flow for a new customer.",
  "What are the most searched topics in the dashboard?",
  "Give me a health summary of the AI infrastructure."
];

function createSession(title, pinned = false) {
  return {
    id: crypto.randomUUID(),
    title,
    pinned,
    archived: false,
    createdAt: Date.now()
  };
}

function sortSessions(sessions) {
  return [...sessions].sort((a, b) => {
    if (a.pinned !== b.pinned) {
      return a.pinned ? -1 : 1;
    }
    return b.createdAt - a.createdAt;
  });
}

function formatTimestamp(date = new Date()) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(ms) {
  if (typeof ms !== "number" || Number.isNaN(ms)) return null;
  if (ms < 1000) return `${Math.max(1, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

export default function App() {
  // Authentication & Session States
  const [token, setToken] = useState("");
  const [authTab, setAuthTab] = useState("login"); // 'login' | 'register'
  
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [error, setError] = useState("");

  // Chat Feed States
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([
    {
      id: "init-2",
      role: "AI",
      label: "RAG Agent",
      time: formatTimestamp(),
      text: "Hello! I am your AI assistant. How can I assist you with your knowledge workspace or vision analysis today?"
    }
  ]);
  const [loading, setLoading] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [fastMode, setFastMode] = useState(true);
  const [health, setHealth] = useState(null);

  // Settings Modal State
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [systemPersona, setSystemPersona] = useState("You are a helpful and professional AI assistant.");
  const [sendOnEnter, setSendOnEnter] = useState(true);
  const [showStarterSuggestions, setShowStarterSuggestions] = useState(true);
  const [showMessageMeta, setShowMessageMeta] = useState(true);
  const [locationEnabled, setLocationEnabled] = useState(false);
  const [locationValue, setLocationValue] = useState("");
  const [locationLoading, setLocationLoading] = useState(false);
  const [automationEnabled, setAutomationEnabled] = useState(false);
  const [automationUrl, setAutomationUrl] = useState("");
  const [automationSyncing, setAutomationSyncing] = useState(false);
  const [automationStatus, setAutomationStatus] = useState("");
  const [automationPages, setAutomationPages] = useState([]);
  const [selectedAutomationUrl, setSelectedAutomationUrl] = useState("");
  const [automationDetail, setAutomationDetail] = useState(null);
  const [automationDetailLoading, setAutomationDetailLoading] = useState(false);
  const [automationDetailError, setAutomationDetailError] = useState("");
  const [automationPanelOpen, setAutomationPanelOpen] = useState(false);
  const [automationDeletingUrl, setAutomationDeletingUrl] = useState("");
  const [openAutomationMenuUrl, setOpenAutomationMenuUrl] = useState("");
  const [expandedSourcePanels, setExpandedSourcePanels] = useState({});
  const [settingsLoaded, setSettingsLoaded] = useState(false);

  // Scroll anchor & inputs
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  // Attachment States
  const [attachedFile, setAttachedFile] = useState(null);
  const [showUploadDropdown, setShowUploadDropdown] = useState(false);
  const documentInputRef = useRef(null);
  const imageInputRef = useRef(null);

  // Chat history list in sidebar
  const [chatHistory, setChatHistory] = useState([
    createSession("Enterprise RAG Ingestion", true),
    createSession("Document Risk Analysis")
  ]);
  const [activeHistoryId, setActiveHistoryId] = useState("");
  const [openHistoryMenuId, setOpenHistoryMenuId] = useState("");
  const [historyNotice, setHistoryNotice] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 760);
  const historyMenuRef = useRef(null);
  const automationMenuRef = useRef(null);

  const displayUserId = useMemo(() => {
    return email.split("@")[0] || email;
  }, [email]);

  const visibleChatHistory = useMemo(() => {
    const activeSessions = chatHistory.filter((session) => !session.archived);
    return sortSessions(activeSessions);
  }, [chatHistory]);

  useEffect(() => {
    const stored = window.localStorage.getItem("aether-profile");
    if (stored) {
      try {
        const profile = JSON.parse(stored);
        if (profile.token) {
          setToken(profile.token);
          setEmail(profile.email || "demo-user");
        }
      } catch {
        window.localStorage.removeItem("aether-profile");
      }
    }
  }, []);

  useEffect(() => {
    const storedSettings = window.localStorage.getItem("aether-settings");
    if (!storedSettings) {
      setSettingsLoaded(true);
      return;
    }

    try {
      const settings = JSON.parse(storedSettings);
      if (typeof settings.systemPersona === "string") setSystemPersona(settings.systemPersona);
      if (typeof settings.fastMode === "boolean") setFastMode(settings.fastMode);
      if (typeof settings.voiceMode === "boolean") setVoiceMode(settings.voiceMode);
      if (typeof settings.sendOnEnter === "boolean") setSendOnEnter(settings.sendOnEnter);
      if (typeof settings.showStarterSuggestions === "boolean") setShowStarterSuggestions(settings.showStarterSuggestions);
      if (typeof settings.showMessageMeta === "boolean") setShowMessageMeta(settings.showMessageMeta);
      if (typeof settings.locationEnabled === "boolean") setLocationEnabled(settings.locationEnabled);
      if (typeof settings.locationValue === "string") setLocationValue(settings.locationValue);
      if (typeof settings.automationEnabled === "boolean") setAutomationEnabled(settings.automationEnabled);
      if (typeof settings.automationUrl === "string") setAutomationUrl(settings.automationUrl);
      if (typeof settings.automationStatus === "string") setAutomationStatus(settings.automationStatus);
    } catch {
      window.localStorage.removeItem("aether-settings");
    } finally {
      setSettingsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!settingsLoaded) return;
    window.localStorage.setItem("aether-settings", JSON.stringify({
      systemPersona,
      fastMode,
      voiceMode,
      sendOnEnter,
      showStarterSuggestions,
      showMessageMeta,
      locationEnabled,
      locationValue,
      automationEnabled,
      automationUrl,
      automationStatus
    }));
  }, [
    settingsLoaded,
    systemPersona,
    fastMode,
    voiceMode,
    sendOnEnter,
    showStarterSuggestions,
    showMessageMeta,
    locationEnabled,
    locationValue,
    automationEnabled,
    automationUrl,
    automationStatus
  ]);

  useEffect(() => {
    if (token) {
      refreshHealth();
      refreshAutomationPages();
    }
  }, [token]);

  useEffect(() => {
    function handleDocumentClick(event) {
      if (!historyMenuRef.current?.contains(event.target)) {
        setOpenHistoryMenuId("");
      }
      if (!automationMenuRef.current?.contains(event.target)) {
        setOpenAutomationMenuUrl("");
      }
    }

    document.addEventListener("mousedown", handleDocumentClick);
    return () => document.removeEventListener("mousedown", handleDocumentClick);
  }, []);

  useEffect(() => {
    function handleResize() {
      setSidebarCollapsed(window.innerWidth < 760);
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    if (!historyNotice) return;

    const timeoutId = window.setTimeout(() => setHistoryNotice(""), 2200);
    return () => window.clearTimeout(timeoutId);
  }, [historyNotice]);

  async function refreshHealth() {
    try {
      const data = await getHealth();
      setHealth(data);
    } catch {
      setHealth({
        status: "offline",
        services: { db: "unknown", redis: "unknown", llm: "unknown", mcp: "unknown" }
      });
    }
  }

  async function refreshAutomationPages() {
    if (!token) return;
    try {
      const data = await listWebKnowledge({ token });
      setAutomationPages(data.entries || []);
    } catch (err) {
      setAutomationPages([]);
      if (err?.status === 401) {
        handleLogout();
      }
    }
  }

  async function openAutomationPage(page) {
    const pageUrl = typeof page === "string" ? page : page?.url;
    if (!pageUrl || !token) return;

    setSelectedAutomationUrl(pageUrl);
    setAutomationPanelOpen(true);
    setAutomationDetailLoading(true);
    setAutomationDetailError("");
    setAutomationDetail(null);

    try {
      const detail = await getWebKnowledgePage({ token, url: pageUrl });
      setAutomationDetail(detail);
    } catch (err) {
      setAutomationDetail(null);
      setAutomationDetailError(err.message || "Unable to load page content.");
      if (err?.status === 401) {
        handleLogout();
      }
    } finally {
      setAutomationDetailLoading(false);
    }
  }

  function closeAutomationPanel() {
    setAutomationPanelOpen(false);
    setSelectedAutomationUrl("");
    setAutomationDetail(null);
    setAutomationDetailError("");
    setAutomationDetailLoading(false);
  }

  async function handleDeleteAutomationPage(page, event) {
    event?.stopPropagation();
    event?.preventDefault();
    const pageUrl = page?.url;
    if (!pageUrl || !token) return;

    const hostLabel = getDisplayHost(page);
    const confirmed = window.confirm(`Remove synced data for ${hostLabel}?\n\n${pageUrl}`);
    if (!confirmed) return;

    setAutomationDeletingUrl(pageUrl);
    setOpenAutomationMenuUrl("");
    try {
      await deleteWebKnowledgePage({ token, url: pageUrl });
      if (selectedAutomationUrl === pageUrl) {
        closeAutomationPanel();
      }
      if (automationUrl === pageUrl) {
        setAutomationUrl("");
        setAutomationEnabled(false);
        setAutomationStatus("Automation source removed");
      }
      await refreshAutomationPages();
      showHistoryNotice("Webpage removed");
    } catch (err) {
      showHistoryNotice(err.message || "Delete failed");
      if (err?.status === 401) {
        handleLogout();
      }
    } finally {
      setAutomationDeletingUrl("");
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Adjust textarea height automatically
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      showHistoryNotice("Copied");
    } catch {
      showHistoryNotice("Copy failed");
    }
  };

  function showHistoryNotice(message) {
    setHistoryNotice(message);
  }

  function openSettingsModal() {
    setShowSettingsModal(true);
    setOpenAutomationMenuUrl("");
    if (token) {
      refreshAutomationPages();
    }
  }

  function closeSettingsModal() {
    setShowSettingsModal(false);
    setOpenAutomationMenuUrl("");
  }

  function withUserLocation(query) {
    const cleanedLocation = locationValue.trim();
    if (!locationEnabled || !cleanedLocation) return query;
    return `[User Location: ${cleanedLocation}]\n\n${query}`;
  }

  function withAutomationPage(query) {
    const cleanedUrl = automationUrl.trim();
    if (!automationEnabled || !cleanedUrl) return query;
    return `[Automation Webpage: ${cleanedUrl}]\nUse the synced webpage as important context when it is relevant.\n\n${query}`;
  }

  function withSettingsContext(query) {
    return withAutomationPage(withUserLocation(query));
  }

  function normalizeAutomationUrl(value) {
    const trimmed = value.trim();
    if (!trimmed) return "";
    if (/^https?:\/\//i.test(trimmed)) return trimmed;
    return `https://${trimmed}`;
  }

  async function syncAutomationPage(urlOverride = automationUrl) {
    const url = normalizeAutomationUrl(urlOverride);
    if (!url) {
      showHistoryNotice("Add a webpage URL");
      return false;
    }

    setAutomationSyncing(true);
    setAutomationStatus("Syncing page...");
    try {
      const result = await seedWebKnowledge({
        token,
        urls: [url],
        maxPagesPerSite: 1
      });
      const message = `${result.pages_fetched || 0} page / ${result.chunks_stored || 0} chunks`;
      setAutomationUrl(url);
      setAutomationStatus(`Synced ${message}`);
      await refreshAutomationPages();
      showHistoryNotice("Webpage synced");
      await openAutomationPage(url);
      return true;
    } catch (err) {
      setAutomationStatus(err.message || "Sync failed");
      showHistoryNotice("Webpage sync failed");
      if (err?.status === 401) {
        handleLogout();
      }
      return false;
    } finally {
      setAutomationSyncing(false);
    }
  }

  async function handleAutomationToggle(checked) {
    setAutomationEnabled(checked);
    if (!checked) {
      setAutomationStatus("Automation disabled");
      return;
    }
    const synced = await syncAutomationPage();
    if (!synced) {
      setAutomationEnabled(false);
    }
  }

  function detectCurrentLocation() {
    if (!navigator.geolocation) {
      showHistoryNotice("Location not supported");
      return;
    }

    setLocationLoading(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        setLocationValue(`${latitude.toFixed(5)}, ${longitude.toFixed(5)}`);
        setLocationEnabled(true);
        setLocationLoading(false);
        showHistoryNotice("Location added");
      },
      () => {
        setLocationLoading(false);
        showHistoryNotice("Location blocked");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
    );
  }

  const renderAnswer = useCallback(
    (text, style) => renderMarkdown(text, copyToClipboard, style),
    [copyToClipboard]
  );

  async function handleLogin(e) {
    if (e) e.preventDefault();
    setAuthLoading(true);
    setError("");

    const cleanedUserId = email.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "user";
    const generatedSessionId = `session-${cleanedUserId}`;

    try {
      const response = await login({
        user_id: cleanedUserId,
        role: "pro_user",
        session_id: generatedSessionId,
        plan: "pro"
      });

      setToken(response.access_token);
      window.localStorage.setItem("aether-profile", JSON.stringify({
        email,
        token: response.access_token
      }));
      handleClearChat(); // start fresh
      await refreshHealth();
      await refreshAutomationPages();
    } catch (err) {
      setError(err.message || "Failed to authenticate workspace.");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleRegister(e) {
    if (e) e.preventDefault();
    setAuthLoading(true);
    setError("");

    const cleanedUserId = email.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "user";
    const generatedSessionId = `session-${cleanedUserId}`;

    try {
      const response = await login({
        user_id: cleanedUserId,
        role: "pro_user",
        session_id: generatedSessionId,
        plan: "pro"
      });

      setToken(response.access_token);
      window.localStorage.setItem("aether-profile", JSON.stringify({
        email,
        token: response.access_token
      }));
      handleClearChat();
      await refreshHealth();
      await refreshAutomationPages();
    } catch (err) {
      setError(err.message || "Failed to provision workspace identity.");
    } finally {
      setAuthLoading(false);
    }
  }

  function handleLogout() {
    setToken("");
    window.localStorage.removeItem("aether-profile");
    setAutomationPages([]);
    closeAutomationPanel();
  }

  async function handleSubmit(e) {
    if (e) e.preventDefault();
    if (!input.trim() && !attachedFile) return;
    if (!token) return;

    const prompt = input.trim();
    const currentAttachment = attachedFile;
    const pendingMsgId = crypto.randomUUID();
    const requestStartedAt = performance.now();
    const requestStartedTime = formatTimestamp();
    
    setInput("");
    setAttachedFile(null);
    setLoading(true);
    setShowUploadDropdown(false);

    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "USR",
        label: "You",
        time: requestStartedTime,
        text: prompt || `Attached a ${currentAttachment?.type}`,
        attachment: currentAttachment
      },
      {
        id: pendingMsgId,
        role: "AI",
        label: "RAG Agent",
        time: requestStartedTime,
        text: "Thinking...",
        pending: true
      }
    ]);

    try {
      let finalResponse = "";
      let responseMeta = null;

      if (currentAttachment && currentAttachment.type === "image") {
        const b64Data = currentAttachment.content.split(",")[1] || currentAttachment.content;
        const res = await analyzeImage({
          token,
          image_name: currentAttachment.name,
          image_bytes_b64: b64Data,
          question: prompt || "Describe this image in detail."
        });
        finalResponse = res.answer;
        responseMeta = res;
      } 
      else if (currentAttachment && currentAttachment.type === "document") {
        const ingestRes = await ingestDocument({
          token,
          filename: currentAttachment.name,
          content: currentAttachment.content,
          contentEncoding: currentAttachment.contentEncoding,
          mimeType: currentAttachment.mimeType
        });

        const documentQuery = prompt
          ? `Using the uploaded document "${currentAttachment.name}", ${prompt}`
          : `Summarize the attached document: ${currentAttachment.name}`;
        const res = await queryAgent({
          token,
          query: withSettingsContext(documentQuery),
          voiceMode,
          fastMode
        });
        finalResponse = res.answer;
        responseMeta = {
          ...res,
          suggested_questions: ingestRes.suggested_questions || []
        };
      } 
      else {
        // Send persona along with query if set
        const finalQuery = systemPersona && systemPersona !== "" 
          ? `[System Persona: ${systemPersona}]\n\n${withSettingsContext(prompt)}` 
          : withSettingsContext(prompt);
          
        const res = await queryAgent({
          token,
          query: finalQuery,
          voiceMode,
          fastMode
        });
        finalResponse = res.answer;
        responseMeta = res;
      }

      const elapsedMs = Math.round(performance.now() - requestStartedAt);
      updateMessage(pendingMsgId, () => ({
        text: finalResponse,
        pending: false,
        time: formatTimestamp(),
        durationMs: elapsedMs,
        serverLatencyMs: responseMeta?.latency_ms,
        source: responseMeta?.source,
        model: responseMeta?.llm_model,
        citations: responseMeta?.citations || [],
        confidence: responseMeta?.confidence,
        sourceCoverage: responseMeta?.source_coverage,
        suggestedQuestions: responseMeta?.suggested_questions || [],
        answerStyle: responseMeta?.answer_style || "detailed"
      }));
    } catch (err) {
      if (err?.status === 401) {
        handleLogout();
        return;
      }
      updateMessage(pendingMsgId, () => ({
        role: "SYS",
        label: "System Error",
        text: `Operation failed: ${err.message}`,
        pending: false,
        time: formatTimestamp(),
        durationMs: Math.round(performance.now() - requestStartedAt)
      }));
    } finally {
      setLoading(false);
    }
  }

  function handleDocumentUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setShowUploadDropdown(false);
    const reader = new FileReader();
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    reader.onload = (event) => {
      const result = String(event.target?.result || "");
      setAttachedFile({
        name: file.name,
        type: "document",
        content: isPdf ? result.split(",", 2)[1] || result : result,
        contentEncoding: isPdf ? "base64" : "text",
        mimeType: file.type || (isPdf ? "application/pdf" : "text/plain")
      });
    };
    if (isPdf) {
      reader.readAsDataURL(file);
    } else {
      reader.readAsText(file);
    }
  }

  function handleImageUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setShowUploadDropdown(false);
    const reader = new FileReader();
    reader.onload = (event) => {
      setAttachedFile({ name: file.name, type: "image", content: event.target?.result });
    };
    reader.readAsDataURL(file);
  }

  function handleNewChat() {
    const nextSessionNumber = chatHistory.filter((session) => !session.archived).length + 1;
    const newSession = createSession(`New Session ${nextSessionNumber}`);
    handleClearChat();
    setChatHistory((current) => sortSessions([newSession, ...current]));
    setActiveHistoryId(newSession.id);
    setOpenHistoryMenuId("");
  }

  function handlePinSession(sessionId) {
    let pinned = false;

    setChatHistory((current) =>
      sortSessions(
        current.map((session) => {
          if (session.id !== sessionId) return session;
          pinned = !session.pinned;
          return { ...session, pinned, createdAt: Date.now() };
        })
      )
    );
    setOpenHistoryMenuId("");
    showHistoryNotice(pinned ? "Chat pinned" : "Chat unpinned");
  }

  async function handleShareSession(session) {
    const shareText = `Chat: ${session.title}`;

    try {
      if (navigator.share) {
        await navigator.share({ title: session.title, text: shareText });
        showHistoryNotice("Share dialog opened");
      } else {
        await navigator.clipboard.writeText(shareText);
        showHistoryNotice("Chat title copied");
      }
    } catch {
      try {
        await navigator.clipboard?.writeText(shareText);
        showHistoryNotice("Chat title copied");
      } catch {
        showHistoryNotice("Unable to share this chat");
      }
    } finally {
      setOpenHistoryMenuId("");
    }
  }

  function handleRenameSession(sessionId, currentTitle) {
    const nextTitle = window.prompt("Rename chat", currentTitle);
    if (!nextTitle || nextTitle.trim() === currentTitle) {
      setOpenHistoryMenuId("");
      return;
    }

    setChatHistory((current) =>
      current.map((session) =>
        session.id === sessionId ? { ...session, title: nextTitle.trim() } : session
      )
    );
    setOpenHistoryMenuId("");
    showHistoryNotice("Chat renamed");
  }

  function handleArchiveSession(sessionId) {
    setChatHistory((current) =>
      current.map((session) =>
        session.id === sessionId ? { ...session, archived: true, pinned: false } : session
      )
    );
    if (activeHistoryId === sessionId) {
      setActiveHistoryId("");
    }
    setOpenHistoryMenuId("");
    showHistoryNotice("Chat archived");
  }

  function handleDeleteSession(sessionId) {
    const session = chatHistory.find((item) => item.id === sessionId);
    if (!window.confirm(`Delete "${session?.title || "this chat"}"?`)) {
      setOpenHistoryMenuId("");
      return;
    }

    setChatHistory((current) => current.filter((session) => session.id !== sessionId));
    if (activeHistoryId === sessionId) {
      setActiveHistoryId("");
    }
    setOpenHistoryMenuId("");
    showHistoryNotice("Chat deleted");
  }

  function handleClearChat() {
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "AI",
        label: "RAG Agent",
        time: formatTimestamp(),
        text: "I'm ready. How can I help you today?"
      }
    ]);
    setAttachedFile(null);
  }

  function updateMessage(messageId, updater) {
    setMessages((current) =>
      current.map((message) => message.id === messageId ? { ...message, ...updater(message) } : message)
    );
  }

  if (!token) {
    return (
      <div className="login-viewport">
        <div className="login-card">
          <div className="login-header">
            <h2>{authTab === "login" ? "Welcome back" : "Create your account"}</h2>
            <p>Access the AI intelligence platform</p>
          </div>

          <form className="login-form" onSubmit={authTab === "login" ? handleLogin : handleRegister}>
            {authTab === "register" && (
              <div className="form-group">
                <label>Full Name</label>
                <input
                  className="form-input"
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="John Doe"
                  required
                />
              </div>
            )}
            <div className="form-group">
              <label>Email Address</label>
              <input
                className="form-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@domain.com"
                required
              />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input
                className="form-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>
            <button className="btn-primary" type="submit" disabled={authLoading}>
              {authLoading ? "Authenticating..." : (authTab === "login" ? "Continue" : "Sign Up")}
            </button>
          </form>

          {error && <div className="login-error">{error}</div>}

          <div className="enroll-trigger">
            {authTab === "login" ? (
               <>Don't have an account? <span onClick={() => { setAuthTab("register"); setError(""); }}>Sign up</span></>
            ) : (
               <>Already have an account? <span onClick={() => { setAuthTab("login"); setError(""); }}>Log in</span></>
            )}
          </div>
        </div>
      </div>
    );
  }

  const profileName = fullName || displayUserId;
  const avatarLetter = (profileName || "U").trim().charAt(0).toUpperCase();

  return (
    <div className="app-container">
      <input type="file" ref={documentInputRef} onChange={handleDocumentUpload} accept=".txt,.md,.pdf,.json" className="hidden" />
      <input type="file" ref={imageInputRef} onChange={handleImageUpload} accept="image/*" className="hidden" />

      {/* LEFT SIDEBAR */}
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={handleNewChat}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            New chat
          </button>
          <button className="toggle-sidebar-btn sidebar-toggle-btn" onClick={() => setSidebarCollapsed(!sidebarCollapsed)} aria-label="Collapse sidebar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
          </button>
        </div>

        <div className="history-container">
          {visibleChatHistory.map((session) => (
            <div key={session.id} className={`history-item ${activeHistoryId === session.id ? "active" : ""}`} onClick={() => setActiveHistoryId(session.id)}>
              <span className="history-title">{session.title}</span>
              <div className="history-actions" ref={openHistoryMenuId === session.id ? historyMenuRef : null}>
                <button
                  aria-label={`Open menu for ${session.title}`}
                  aria-expanded={openHistoryMenuId === session.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenHistoryMenuId((current) => current === session.id ? "" : session.id);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
                </button>
                {openHistoryMenuId === session.id && (
                  <div className="history-menu" role="menu" onClick={(e) => e.stopPropagation()}>
                    <button className="history-menu-item" role="menuitem" onClick={() => handleShareSession(session)}>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M16 6 12 2 8 6"/><path d="M12 2v13"/></svg>
                      Share
                    </button>
                    <button className="history-menu-item" role="menuitem" onClick={() => handleRenameSession(session.id, session.title)}>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="m16.5 3.5 4 4L7 21H3v-4L16.5 3.5z"/></svg>
                      Rename
                    </button>
                    <div className="history-menu-separator" />
                    <button className="history-menu-item" role="menuitem" onClick={() => handlePinSession(session.id)}>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 4 5 5-4 4v6l-4-4-5 5-2-2 5-5-4-4 4-4h6Z"/></svg>
                      {session.pinned ? "Unpin chat" : "Pin chat"}
                    </button>
                    <button className="history-menu-item" role="menuitem" onClick={() => handleArchiveSession(session.id)}>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/></svg>
                      Archive
                    </button>
                    <button className="history-menu-item danger" role="menuitem" onClick={() => handleDeleteSession(session.id)}>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6 18 20a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <button className="footer-btn" onClick={openSettingsModal}>
             <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
             Settings
          </button>
          <div className="user-profile" onClick={handleLogout}>
            <div className="avatar">{avatarLetter}</div>
            <div style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{profileName}</div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
          </div>
        </div>
      </aside>

      {/* CHAT AREA */}
      {!sidebarCollapsed && <div className="sidebar-backdrop" onClick={() => setSidebarCollapsed(true)} />}
      <main className={`chat-viewport ${!sidebarCollapsed ? "drawer-open" : ""} ${automationPanelOpen ? "detail-open" : ""}`}>
        <button
          className="mobile-sidebar-open-btn"
          onClick={() => setSidebarCollapsed(false)}
          aria-label="Open sidebar"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
        </button>
        {historyNotice && <div className="history-notice">{historyNotice}</div>}
        <div className="messages-container">
          {messages.length === 1 && messages[0].role === "AI" ? (
            <div className="welcome-screen">
               <div className="welcome-logo">
                 <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a10 10 0 1 0 10 10H12V2Z"/><path d="M12 12 2.1 7.1"/><path d="m12 12 9.9 4.9"/></svg>
               </div>
               <h2 className="welcome-title">How can I help you today?</h2>
               {showStarterSuggestions && (
                 <div className="starter-prompts">
                   {starterPrompts.map((p, i) => (
                     <button key={i} className="starter-btn" onClick={() => setInput(p)}>
                       {p}
                     </button>
                   ))}
                 </div>
               )}
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                <div className="message-content-inner">
                  <div className="message-avatar">
                    {msg.role === "USR" ? avatarLetter : (msg.role === "SYS" ? "!" : "AI")}
                  </div>
                  <div className="message-body">
                    {showMessageMeta && (
                      <div className="message-meta">
                        <span className="message-label">{msg.label}</span>
                        <span>{msg.time}</span>
                        {formatDuration(msg.durationMs) && (
                          <span>response {formatDuration(msg.durationMs)}</span>
                        )}
                        {msg.serverLatencyMs && msg.serverLatencyMs !== msg.durationMs && (
                          <span>server {formatDuration(msg.serverLatencyMs)}</span>
                        )}
                      </div>
                    )}
                    {msg.attachment && (
                      <div className="attachment-badge">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                        {msg.attachment.name}
                      </div>
                    )}
                    {msg.pending ? (
                      <span style={{ color: 'var(--text-muted)' }}>Thinking...</span>
                    ) : (
                      <div className={`markdown-body ${msg.answerStyle ? `markdown-${msg.answerStyle}` : ""}`}>
                        {renderAnswer(msg.text, msg.answerStyle)}
                      </div>
                    )}
                    
                    {msg.role === "AI" && !msg.pending && (
                      <>
                      {(msg.source === "database" || msg.source === "web_search" || msg.citations?.length > 0 || (msg.sourceCoverage && msg.sourceCoverage !== "none")) && (
                        <div className="rag-insights">
                          {typeof msg.confidence === "number" && msg.source !== "llm" && (
                            <span>Confidence {Math.round(msg.confidence * 100)}%</span>
                          )}
                          {msg.sourceCoverage && msg.sourceCoverage !== "none" && <span>Coverage {msg.sourceCoverage}</span>}
                          {msg.citations?.length > 0 && (
                            <button
                              type="button"
                              className={`rag-insight-btn sources-toggle ${expandedSourcePanels[msg.id] ? "expanded" : ""}`}
                              onClick={() =>
                                setExpandedSourcePanels((current) => ({
                                  ...current,
                                  [msg.id]: !current[msg.id]
                                }))
                              }
                              aria-expanded={Boolean(expandedSourcePanels[msg.id])}
                              aria-controls={`sources-panel-${msg.id}`}
                            >
                              <span>{msg.citations.length} sources</span>
                              <svg
                                className="sources-chevron"
                                width="14"
                                height="14"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                aria-hidden="true"
                              >
                                <polyline points="6 9 12 15 18 9" />
                              </svg>
                            </button>
                          )}
                        </div>
                      )}
                      {msg.citations?.length > 0 && expandedSourcePanels[msg.id] && (
                        <div className="source-list" id={`sources-panel-${msg.id}`}>
                          <div className="source-list-title">Sources</div>
                          {msg.citations.map((citation, index) => (
                            <div key={`${msg.id}-citation-${index}`} className="source-item">
                              {citation}
                            </div>
                          ))}
                        </div>
                      )}
                      {msg.suggestedQuestions?.length > 0 && (
                        <div className="suggested-question-row">
                          {msg.suggestedQuestions.map((question, index) => (
                            <button
                              key={`${msg.id}-suggestion-${index}`}
                              className="suggested-question"
                              onClick={() => setInput(question)}
                            >
                              {question}
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="message-actions">
                        <button className="action-btn" onClick={() => copyToClipboard(msg.text)} title="Copy message">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                          Copy
                        </button>
                      </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area-wrapper">
          <div className="input-container">
            {attachedFile && (
              <div className="attached-file-preview">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                <span className="attached-file-name">{attachedFile.name}</span>
                <button className="remove-file-btn" onClick={() => setAttachedFile(null)}>×</button>
              </div>
            )}
            
            <div className="input-box">
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (sendOnEnter && e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
                placeholder="Message ChatGPT..."
                rows={1}
              />
              
              <div className="input-actions-bottom">
                <button className="attach-btn" onClick={() => setShowUploadDropdown(!showUploadDropdown)} title="Attach File">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>
                  {showUploadDropdown && (
                    <div className="attachment-dropdown">
                      <div className="attachment-option" onClick={(e) => { e.stopPropagation(); documentInputRef.current?.click(); }}>
                         <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                         Upload Document
                      </div>
                      <div className="attachment-option" onClick={(e) => { e.stopPropagation(); imageInputRef.current?.click(); }}>
                         <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                         Upload Image
                      </div>
                    </div>
                  )}
                </button>

                <button className="submit-btn" onClick={handleSubmit} disabled={loading || (!input.trim() && !attachedFile)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
                </button>
              </div>
            </div>
            <div className="disclaimer">
              Responses include timestamp and total answer time. Verify important information.
            </div>
          </div>
        </div>
      </main>

      {automationPanelOpen && (
        <>
          <div className="detail-panel-backdrop" onClick={closeAutomationPanel} />
          <aside className="detail-panel open" aria-label="Scraped page viewer">
            <div className="detail-panel-header">
              <div className="detail-panel-heading">
                <span className="detail-panel-eyebrow">Synced webpage</span>
                <h2 className="detail-panel-title">
                  {automationDetail?.title || getDisplayHost(automationDetail) || "Page content"}
                </h2>
                {selectedAutomationUrl && (
                  <a
                    className="detail-panel-source-link"
                    href={selectedAutomationUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {selectedAutomationUrl}
                  </a>
                )}
              </div>
              <button type="button" className="detail-panel-close" onClick={closeAutomationPanel} aria-label="Close panel">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>

            <div className="detail-panel-stats">
              <div className="detail-stat">
                <span className="detail-stat-label">Host</span>
                <span className="detail-stat-value">{automationDetail?.host || getDisplayHost(automationDetail)}</span>
              </div>
              <div className="detail-stat">
                <span className="detail-stat-label">Chunks</span>
                <span className="detail-stat-value">{formatStatNumber(automationDetail?.chunks || 0)}</span>
              </div>
              <div className="detail-stat">
                <span className="detail-stat-label">Words</span>
                <span className="detail-stat-value">{formatStatNumber(automationDetail?.word_count || 0)}</span>
              </div>
              <div className="detail-stat">
                <span className="detail-stat-label">Updated</span>
                <span className="detail-stat-value">{formatPageTimestamp(automationDetail?.last_updated)}</span>
              </div>
            </div>

            <div className="detail-panel-body">
              {automationDetailLoading && (
                <div className="detail-panel-state">Loading formatted page content...</div>
              )}
              {!automationDetailLoading && automationDetailError && (
                <div className="detail-panel-state error">{automationDetailError}</div>
              )}
              {!automationDetailLoading && !automationDetailError && automationDetail && (
                <>
                  {automationDetail.excerpt && (
                    <div className="detail-panel-excerpt">
                      <span className="detail-excerpt-label">Summary excerpt</span>
                      <p>{automationDetail.excerpt}</p>
                    </div>
                  )}
                  <div className="detail-panel-document markdown-body">
                    {automationDetail.sections?.length > 0 ? (
                      automationDetail.sections.map((section, index) => (
                        <section key={`${selectedAutomationUrl}-section-${index}`} className="detail-document-section">
                          {section.heading && <h3 className="detail-section-heading">{section.heading}</h3>}
                          {(section.paragraphs || []).map((paragraph, paragraphIndex) => (
                            <div key={`${index}-${paragraphIndex}`} className="detail-section-paragraph">
                              {renderAnswer(paragraph)}
                            </div>
                          ))}
                        </section>
                      ))
                    ) : (
                      renderAnswer(pageDetailToMarkdown(automationDetail))
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="detail-panel-footer">
              <button
                type="button"
                className="detail-footer-btn"
                onClick={() => automationDetail && copyToClipboard(pageDetailToMarkdown(automationDetail))}
                disabled={!automationDetail}
              >
                Copy content
              </button>
              <button
                type="button"
                className="detail-footer-btn primary"
                onClick={() => {
                  if (selectedAutomationUrl) {
                    setAutomationUrl(selectedAutomationUrl);
                    setAutomationEnabled(true);
                  }
                  closeAutomationPanel();
                  openSettingsModal();
                }}
              >
                Use in chat
              </button>
            </div>
          </aside>
        </>
      )}

      {/* SETTINGS MODAL */}
      {showSettingsModal && (
        <div className="modal-overlay" onClick={closeSettingsModal}>
          <div className="modal-content settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Settings</h3>
              <button className="close-modal-btn" onClick={closeSettingsModal}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
            <div className="modal-body">
              <div className="settings-panel">
                <div className="settings-section">
                  <div className="settings-section-title">Location</div>
                  <div className="settings-grid single">
                    <label className="settings-card location-card">
                      <span className="settings-icon">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s7-5.2 7-11a7 7 0 0 0-14 0c0 5.8 7 11 7 11Z"/><circle cx="12" cy="10" r="2.5"/></svg>
                      </span>
                      <span className="settings-copy">
                        <strong>Use location context</strong>
                        <span>When enabled, your location is added to questions that need local context.</span>
                      </span>
                      <input type="checkbox" checked={locationEnabled} onChange={(e) => setLocationEnabled(e.target.checked)} />
                      <span className="settings-switch" />
                    </label>
                  </div>
                  <div className="location-controls">
                    <input
                      className="settings-location-input"
                      value={locationValue}
                      onChange={(e) => setLocationValue(e.target.value)}
                      placeholder="Add city, region, or coordinates"
                    />
                    <button type="button" className="settings-detect-btn" onClick={detectCurrentLocation} disabled={locationLoading}>
                      {locationLoading ? "Detecting..." : "Detect"}
                    </button>
                  </div>
                  <p className="settings-help-text">
                    Keep it off if you do not want location sent with your questions.
                  </p>
                </div>

                <div className="settings-section settings-automation-section">
                  <div className="settings-section-title">Web Automation</div>
                  <div className="settings-grid single">
                    <label className="settings-card location-card">
                      <span className="settings-icon">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.1 0l2.1-2.1a5 5 0 0 0-7.1-7.1L11 4.9"/><path d="M14 11a5 5 0 0 0-7.1 0l-2.1 2.1a5 5 0 0 0 7.1 7.1L13 19.1"/></svg>
                      </span>
                      <span className="settings-copy">
                        <strong>Webpage automation</strong>
                        <span>Sync pages into your knowledge base and use them in chat when relevant.</span>
                      </span>
                      <input type="checkbox" checked={automationEnabled} onChange={(e) => handleAutomationToggle(e.target.checked)} />
                      <span className="settings-switch" />
                    </label>
                  </div>
                  <div className="location-controls settings-automation-controls">
                    <input
                      className="settings-location-input"
                      value={automationUrl}
                      onChange={(e) => setAutomationUrl(e.target.value)}
                      placeholder="Paste URL to scrape"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          syncAutomationPage();
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="settings-detect-btn settings-sync-btn"
                      onClick={() => syncAutomationPage()}
                      disabled={automationSyncing || !automationUrl.trim()}
                    >
                      {automationSyncing ? "Syncing..." : "Sync"}
                    </button>
                  </div>
                  <p className="settings-help-text">
                    Paste a URL and sync to capture page data. Click a synced page to view formatted content in the right panel.
                  </p>
                  {automationStatus && <p className="settings-status-text">{automationStatus}</p>}

                  {automationPages.length === 0 ? (
                    <div className="settings-automation-empty">
                      No synced webpages yet. Paste a URL and sync to capture page data.
                    </div>
                  ) : (
                    <div className="settings-automation-list">
                      {automationPages.map((page) => (
                        <div
                          key={page.url}
                          className={`settings-automation-row ${selectedAutomationUrl === page.url ? "active" : ""}`}
                        >
                          <button
                            type="button"
                            className="settings-automation-main"
                            onClick={() => {
                              openAutomationPage(page);
                              closeSettingsModal();
                            }}
                          >
                            <div className="settings-automation-meta">
                              <span>{getDisplayHost(page)}</span>
                              <span>{page.chunks} chunks</span>
                            </div>
                            <div className="settings-automation-url" title={page.url}>{page.url}</div>
                            <div className="settings-automation-preview">{page.preview || "No preview available."}</div>
                          </button>
                          <div
                            className="settings-automation-actions"
                            ref={openAutomationMenuUrl === page.url ? automationMenuRef : null}
                          >
                            <button
                              type="button"
                              className="settings-automation-menu-btn"
                              aria-label={`Open actions for ${getDisplayHost(page)}`}
                              aria-expanded={openAutomationMenuUrl === page.url}
                              onClick={(event) => {
                                event.stopPropagation();
                                setOpenAutomationMenuUrl((current) => (current === page.url ? "" : page.url));
                              }}
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="1" />
                                <circle cx="12" cy="5" r="1" />
                                <circle cx="12" cy="19" r="1" />
                              </svg>
                            </button>
                            {openAutomationMenuUrl === page.url && (
                              <div className="history-menu settings-automation-menu" role="menu" onClick={(e) => e.stopPropagation()}>
                                <button
                                  className="history-menu-item"
                                  role="menuitem"
                                  onClick={() => {
                                    setOpenAutomationMenuUrl("");
                                    openAutomationPage(page);
                                    closeSettingsModal();
                                  }}
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12Z"/><circle cx="12" cy="12" r="3"/></svg>
                                  View content
                                </button>
                                <button
                                  className="history-menu-item"
                                  role="menuitem"
                                  onClick={() => {
                                    setOpenAutomationMenuUrl("");
                                    setAutomationUrl(page.url);
                                    setAutomationEnabled(true);
                                    setAutomationStatus(`Using ${getDisplayHost(page)} in chat`);
                                    showHistoryNotice("Automation source updated");
                                  }}
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                                  Use in chat
                                </button>
                                <button
                                  className="history-menu-item"
                                  role="menuitem"
                                  onClick={() => {
                                    setOpenAutomationMenuUrl("");
                                    syncAutomationPage(page.url);
                                  }}
                                  disabled={automationSyncing}
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
                                  Re-sync page
                                </button>
                                <div className="history-menu-separator" />
                                <button
                                  className="history-menu-item danger"
                                  role="menuitem"
                                  onClick={(event) => handleDeleteAutomationPage(page, event)}
                                  disabled={automationDeletingUrl === page.url}
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6 18 20a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                                  {automationDeletingUrl === page.url ? "Deleting..." : "Delete"}
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
