const LANGUAGE_LABELS = {
  python: "Python",
  py: "Python",
  javascript: "JavaScript",
  js: "JavaScript",
  typescript: "TypeScript",
  ts: "TypeScript",
  json: "JSON",
  html: "HTML",
  css: "CSS",
  bash: "Bash",
  shell: "Shell",
  sql: "SQL",
  java: "Java",
  cpp: "C++",
  c: "C",
  go: "Go",
  rust: "Rust",
  text: "Text"
};

const PY_KEYWORDS = new Set([
  "def", "return", "import", "from", "if", "else", "elif", "for", "while", "class",
  "in", "as", "True", "False", "None", "with", "lambda", "pass", "break", "continue",
  "try", "except", "finally", "raise", "yield", "global", "nonlocal", "and", "or", "not", "is"
]);

const JS_KEYWORDS = new Set([
  "const", "let", "var", "function", "return", "if", "else", "for", "while", "class",
  "import", "from", "export", "default", "async", "await", "new", "true", "false", "null", "undefined"
]);

function languageLabel(lang) {
  const key = (lang || "").trim().toLowerCase();
  return LANGUAGE_LABELS[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1) : "Code");
}

const CODE_LINE_BREAK_PATTERNS = [
  /\s+(?=#)/g,
  /\s+(?=import\s)/g,
  /\s+(?=from\s+[\w.]+\s+import\s)/g,
  /\s+(?=def\s)/g,
  /\s+(?=class\s)/g,
  /\s+(?=if\s)/g,
  /\s+(?=elif\s)/g,
  /\s+(?=else:)/g,
  /\s+(?=for\s)/g,
  /\s+(?=while\s)/g,
  /\s+(?=try:)/g,
  /\s+(?=except\s)/g,
  /\s+(?=finally:)/g,
  /\s+(?=with\s)/g,
  /\s+(?=return\s)/g,
  /\s+(?=print\s*\()/g,
  /\s+(?=[A-Za-z_][\w]*\s*=\s)/g
];

function formatCollapsedCode(code) {
  if (!code) return "";
  if (code.includes("\n") && code.split("\n").length >= 4) {
    return code.trim();
  }

  let formatted = code.trim();

  // Strong fallback: many LLMs collapse code by joining lines with 2+ spaces.
  // Splitting on that gives readable, line-oriented code across languages.
  if (!formatted.includes("\n") && /\s{2,}/.test(formatted)) {
    formatted = formatted.replace(/\s{2,}/g, "\n");
  }

  for (const pattern of CODE_LINE_BREAK_PATTERNS) {
    formatted = formatted.replace(pattern, "\n");
  }
  return formatted
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line, index, lines) => line.length > 0 || (index > 0 && lines[index + 1]))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function normalizeAnswerText(text, style = "detailed") {
  if (!text) return "";

  let normalized = text.replace(/\r\n/g, "\n");
  if (normalized.includes("\\n")) {
    normalized = normalized.replace(/\\n/g, "\n");
  }

  normalized = normalized.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n");

  if (style === "brief") {
    normalized = normalized.replace(/([.!?])\s+(\*\*[A-Za-z])/g, "$1\n\n$2");
  }

  normalized = normalized.replace(
    /^([A-Za-z][^\n]{4,}?→[^\n]+)$/gm,
    (line) => `\n${line.trim()}\n`
  );

  normalized = normalized.replace(/```([a-zA-Z0-9_+-]*)\s*([\s\S]*?)```/g, (match, lang, code) => {
    const language = (lang || "text").trim();
    const body = formatCollapsedCode(code);
    return `\n\n\`\`\`${language}\n${body}\n\`\`\`\n\n`;
  });

  normalized = normalized.replace(
    /(^|\n)(Output|Sample output|Result):\s*(?!\n)/gi,
    "\n\n$2:\n\n"
  );

  normalized = normalized.replace(/([.!?])\s+(##\s)/g, "$1\n\n$2");
  normalized = normalized.replace(/([.!?])\s+(\*\*[A-Z])/g, "$1\n\n$2");

  return normalized.trim();
}

function splitAnswerLead(text) {
  const match = text.match(/^(Here is what I found[.:]?\s*)([\s\S]*)$/i);
  if (!match) {
    return { lead: null, body: text };
  }
  return {
    lead: match[1].trim().replace(/[.:]$/, ""),
    body: match[2].trim()
  };
}

function highlightLine(line, keywords) {
  const tokens = [];
  const pattern = /("[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*'|`[^`]*`)|(\b[A-Za-z_][\w]*\b)|(\b\d+\.?\d*\b)|(\s+|[^\s\w]+)/g;
  let match;
  let index = 0;

  while ((match = pattern.exec(line)) !== null) {
    const value = match[0];
    if (!value) continue;

    if (match[1]) {
      tokens.push(<span key={index++} className="tok-string">{value}</span>);
      continue;
    }
    if (match[2]) {
      const word = value;
      if (keywords.has(word)) {
        tokens.push(<span key={index++} className="tok-keyword">{word}</span>);
      } else if (/^[A-Z]/.test(word)) {
        tokens.push(<span key={index++} className="tok-type">{word}</span>);
      } else if (line.indexOf(word) > 0 && line[line.indexOf(word) - 1] === ".") {
        tokens.push(<span key={index++} className="tok-function">{word}</span>);
      } else {
        tokens.push(<span key={index++} className="tok-plain">{word}</span>);
      }
      continue;
    }
    if (match[3]) {
      tokens.push(<span key={index++} className="tok-number">{value}</span>);
      continue;
    }
    tokens.push(<span key={index++} className="tok-plain">{value}</span>);
  }

  return tokens.length ? tokens : line;
}

function highlightPython(code) {
  return code.split("\n").map((line, lineIndex) => {
    const commentIndex = line.indexOf("#");
    if (commentIndex >= 0) {
      const codePart = line.slice(0, commentIndex);
      const commentPart = line.slice(commentIndex);
      return (
        <span key={`line-${lineIndex}`} className="md-code-line">
          {codePart ? highlightLine(codePart, PY_KEYWORDS) : null}
          <span className="tok-comment">{commentPart}</span>
          {lineIndex < code.split("\n").length - 1 ? "\n" : null}
        </span>
      );
    }
    return (
      <span key={`line-${lineIndex}`} className="md-code-line">
        {highlightLine(line, PY_KEYWORDS)}
        {lineIndex < code.split("\n").length - 1 ? "\n" : null}
      </span>
    );
  });
}

function highlightJavaScript(code) {
  return code.split("\n").map((line, lineIndex) => {
    const commentMatch = line.match(/^(\s*)(\/\/.*)$/);
    if (commentMatch) {
      return (
        <span key={`line-${lineIndex}`} className="md-code-line">
          <span className="tok-plain">{commentMatch[1]}</span>
          <span className="tok-comment">{commentMatch[2]}</span>
          {lineIndex < code.split("\n").length - 1 ? "\n" : null}
        </span>
      );
    }
    return (
      <span key={`line-${lineIndex}`} className="md-code-line">
        {highlightLine(line, JS_KEYWORDS)}
        {lineIndex < code.split("\n").length - 1 ? "\n" : null}
      </span>
    );
  });
}

function highlightCode(code, lang) {
  const normalized = (lang || "").trim().toLowerCase();
  if (normalized === "python" || normalized === "py") {
    return highlightPython(code);
  }
  if (["javascript", "js", "typescript", "ts"].includes(normalized)) {
    return highlightJavaScript(code);
  }
  return code;
}

function CodeBlock({ lang, codeText, variant = "code", onCopy }) {
  const label = variant === "output" ? "Output" : languageLabel(lang);
  return (
    <div className={`md-code-block ${variant === "output" ? "md-output-block" : ""}`}>
      <div className="md-code-header">
        <div className="md-code-lang">
          <span className={`md-lang-badge ${variant === "output" ? "output" : ""}`} aria-hidden="true" />
          <span>{label}</span>
        </div>
        <div className="md-code-actions">
          <button
            type="button"
            className="copy-code-btn"
            onClick={() => onCopy?.(codeText)}
            title="Copy code"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            Copy
          </button>
        </div>
      </div>
      <pre className="md-code-content">
        <code>{highlightCode(codeText, lang)}</code>
      </pre>
    </div>
  );
}

export function inlineFormat(text) {
  if (!text) return null;
  const parts = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let match;
  let idx = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={idx++}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      parts.push(<em key={idx++}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("`")) {
      parts.push(<code key={idx++} className="md-inline-code">{token.slice(1, -1)}</code>);
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        parts.push(
          <a key={idx++} className="md-link" href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>
        );
      } else {
        parts.push(token);
      }
    }
    last = regex.lastIndex;
  }

  if (last < text.length) {
    parts.push(text.slice(last));
  }

  return parts.length > 0 ? parts : text;
}

const STYLE_CLASS = {
  brief: "md-style-brief",
  detailed: "md-style-detailed",
  coding: "md-style-coding"
};

export function renderMarkdown(text, onCopy, style = "detailed") {
  if (!text) return null;

  const answerStyle = STYLE_CLASS[style] ? style : "detailed";
  const normalized = normalizeAnswerText(text, answerStyle);
  const { lead, body } = splitAnswerLead(normalized);
  const lines = body.split("\n");
  const elements = [];

  if (lead) {
    elements.push(
      <div key="answer-lead" className="md-answer-lead">
        {lead}
      </div>
    );
  }

  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      const codeText = codeLines.join("\n");
      const variant = ["output", "result", "console"].includes(lang.toLowerCase()) ? "output" : "code";
      elements.push(
        <CodeBlock
          key={`code-${i}-${elements.length}`}
          lang={variant === "output" ? "" : lang}
          codeText={codeText}
          variant={variant}
          onCopy={onCopy}
        />
      );
      i += 1;
      continue;
    }

    if (/^output:\s*$/i.test(line.trim())) {
      elements.push(
        <p key={`output-label-${i}`} className="md-output-label">
          Output
        </p>
      );
      i += 1;
      if (i < lines.length && lines[i].trim().startsWith("```")) {
        continue;
      }
      if (i < lines.length && lines[i].trim()) {
        const outputText = lines[i].trim();
        elements.push(
          <CodeBlock
            key={`output-inline-${i}`}
            lang="output"
            codeText={outputText}
            variant="output"
            onCopy={onCopy}
          />
        );
        i += 1;
      }
      continue;
    }

    if (line.trim().startsWith("|") && i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) {
      const tableRows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].split("|").filter((cell) => cell.trim() !== "");
        tableRows.push(cells);
        i += 1;
      }

      if (tableRows.length > 2) {
        elements.push(
          <div key={`table-${i}`} className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>
                  {tableRows[0].map((cell, idx) => (
                    <th key={idx}>{inlineFormat(cell.trim())}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableRows.slice(2).map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {row.map((cell, idx) => (
                      <td key={idx}>{inlineFormat(cell.trim())}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const Tag = `h${Math.min(level + 2, 6)}`;
      elements.push(
        <Tag key={`h-${i}`} className={`md-heading md-h${Math.min(level, 3)}`}>
          {inlineFormat(headingMatch[2])}
        </Tag>
      );
      i += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      elements.push(
        <blockquote key={`quote-${i}`} className="md-quote">
          {quoteLines.map((quoteLine, quoteIndex) => (
            <p key={quoteIndex} className="md-para md-quote-line">
              {inlineFormat(quoteLine)}
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    if (/^\s*[-*+]\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s/.test(lines[i])) {
        items.push(
          <li key={`li-${i}`}>{inlineFormat(lines[i].replace(/^\s*[-*+]\s/, ""))}</li>
        );
        i += 1;
      }
      elements.push(<ul key={`ul-${i}`} className="md-list">{items}</ul>);
      continue;
    }

    if (/^\s*\d+\.\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) {
        items.push(
          <li key={`oli-${i}`}>{inlineFormat(lines[i].replace(/^\s*\d+\.\s/, ""))}</li>
        );
        i += 1;
      }
      elements.push(<ol key={`ol-${i}`} className="md-list md-ordered-list">{items}</ol>);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      elements.push(<hr key={`hr-${i}`} className="md-hr" />);
      i += 1;
      continue;
    }

    const sourceMatch = line.match(/^\*Source:\s*(.+)\*$/i);
    if (sourceMatch) {
      elements.push(
        <div key={`source-${i}`} className="md-source-footer">
          Source: <span>{sourceMatch[1]}</span>
        </div>
      );
      i += 1;
      continue;
    }

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const paragraphLines = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !/^(#{1,6})\s/.test(lines[i]) &&
      !/^\s*[-*+]\s/.test(lines[i]) &&
      !/^\s*\d+\.\s/.test(lines[i]) &&
      !/^>\s?/.test(lines[i]) &&
      !lines[i].trim().startsWith("|") &&
      !/^output:\s*$/i.test(lines[i].trim())
    ) {
      paragraphLines.push(lines[i]);
      i += 1;
    }

    const paragraphText = paragraphLines.join(" ");
    const isComparison = /→/.test(paragraphText) && !/^\s*[-*+]/.test(paragraphLines[0]);
    const isExampleLead = /^\*\*Example:\*\*/i.test(paragraphText.trim());

    elements.push(
      <p
        key={`p-${i}`}
        className={[
          "md-para",
          isComparison ? "md-comparison" : "",
          isExampleLead ? "md-example" : ""
        ].filter(Boolean).join(" ")}
      >
        {inlineFormat(paragraphText)}
      </p>
    );
  }

  const styleClass = STYLE_CLASS[answerStyle] || STYLE_CLASS.detailed;
  return (
    <article className={`md-document md-answer-document ${styleClass}`}>
      {elements}
    </article>
  );
}
