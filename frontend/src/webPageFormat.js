export function formatPageTimestamp(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function formatStatNumber(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "0";
  return value.toLocaleString();
}

export function pageDetailToMarkdown(detail) {
  if (!detail) return "";
  if (detail.sections?.length) {
    return detail.sections
      .map((section) => {
        const heading = section.heading ? `## ${section.heading}\n\n` : "";
        const paragraphs = (section.paragraphs || []).join("\n\n");
        return `${heading}${paragraphs}`.trim();
      })
      .filter(Boolean)
      .join("\n\n");
  }
  return detail.body || "";
}

export function getDisplayHost(page) {
  if (!page) return "web";
  return page.host || page.url?.replace(/^https?:\/\//i, "").split("/")[0] || "web";
}
