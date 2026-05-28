const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

async function parseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || data.message || "Request failed.");
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function login({ user_id, role, session_id, plan }) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, role, session_id, plan })
  });
  return parseJson(response);
}

export async function queryAgent({ token, query, voiceMode, fastMode }) {
  const response = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Response-Mode": voiceMode ? "voice" : "text",
      "X-Fast-Mode": fastMode ? "true" : "false"
    },
    body: JSON.stringify({ query })
  });
  return parseJson(response);
}

export async function getDashboard(token) {
  const response = await fetch(`${API_BASE_URL}/dashboard`, {
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  return parseJson(response);
}

export async function getHealth() {
  const response = await fetch(`${API_BASE_URL}/health`);
  return parseJson(response);
}

export async function ingestDocument({ token, filename, content, contentEncoding, mimeType, metadata = {} }) {
  const response = await fetch(`${API_BASE_URL}/input`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      filename,
      content,
      content_encoding: contentEncoding,
      mime_type: mimeType,
      metadata
    })
  });
  return parseJson(response);
}

export async function seedWebKnowledge({ token, urls, maxPagesPerSite = 1 }) {
  const response = await fetch(`${API_BASE_URL}/knowledge/web/seed`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      urls,
      max_pages_per_site: maxPagesPerSite
    })
  });
  return parseJson(response);
}

export async function listWebKnowledge({ token }) {
  const response = await fetch(`${API_BASE_URL}/knowledge/web/list`, {
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  return parseJson(response);
}

export async function getWebKnowledgePage({ token, url }) {
  const params = new URLSearchParams({ url });
  const response = await fetch(`${API_BASE_URL}/knowledge/web/page?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  return parseJson(response);
}

export async function deleteWebKnowledgePage({ token, url }) {
  const params = new URLSearchParams({ url });
  const response = await fetch(`${API_BASE_URL}/knowledge/web/page?${params.toString()}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  return parseJson(response);
}

export async function analyzeImage({ token, image_name, image_bytes_b64, question, contains_sensitive_data = false, confirmation = true }) {
  const response = await fetch(`${API_BASE_URL}/vision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      image_name,
      image_bytes_b64,
      question,
      contains_sensitive_data,
      confirmation
    })
  });
  return parseJson(response);
}
