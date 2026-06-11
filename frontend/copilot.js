/* TaxGlobal AI — Copilot real-backend transport (M3.5).
   Streams POST /api/assistant/stream (SSE) into the EXISTING chat UI in
   index.html (#cpMsgs bubbles). All dynamic text — especially LLM
   answer_text — is HTML-escaped before touching innerHTML. */
(function () {
  var API_BASE_URL = "http://127.0.0.1:8000";

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Minimal markdown on ALREADY-ESCAPED text: **bold**, `code`, newlines.
  function renderMarkdownEscaped(text) {
    var safe = escapeHtml(text);
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/`([^`\n]+)`/g, '<span class="cp-cite">$1</span>');
    safe = safe.replace(/\n/g, "<br>");
    return safe;
  }

  // ---------- structured answer rendering ----------

  function describeAnswer(answer) {
    if (!answer || typeof answer !== "object") return "";
    if (answer.type === "clarification") {
      var msg = answer.message || "";
      if (answer.missing_params && answer.missing_params.length) {
        msg += "\n缺少参数: " + answer.missing_params.join(", ");
      }
      if (answer.available_topics && answer.available_topics.length) {
        msg += "\n可以问: " + answer.available_topics.join(" / ");
      }
      return msg;
    }
    if (answer.type === "error") return answer.message || "请求未能完成。";
    if (answer.type === "knowledge") {
      var parts = [];
      var results = answer.results || [];
      for (var i = 0; i < Math.min(results.length, 3); i++) {
        var item = results[i] || {};
        if (item.text) parts.push(String(item.text));
      }
      return parts.length ? parts.join("\n\n") : "没有找到相关的知识条目。";
    }
    if (answer.type === "skill_result") {
      var data = answer.data || {};
      if (data.status && data.status !== "ok") {
        // Never imply a computed answer for not_covered / invalid_input.
        return "引擎未能完成这次计算（" + String(data.status) + "）。" + (data.reason ? "\n原因: " + String(data.reason) : "");
      }
      return "已用规则引擎完成计算：";
    }
    return "";
  }

  function formatMoney(value) {
    var amount = Number(value);
    if (!isFinite(amount)) return String(value);
    return "$" + amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function skillRows(data) {
    // The engine breakdown is curated for display — render it verbatim.
    // Zero rows stay: "excluded_income $0.00" IS the answer for a failed
    // FEIE test; hiding it would invert the meaning.
    var rows = [];
    if (data && Array.isArray(data.breakdown)) {
      for (var i = 0; i < data.breakdown.length; i++) {
        var item = data.breakdown[i] || {};
        if (typeof item.label !== "string" || typeof item.amount !== "number") continue;
        rows.push([item.label, formatMoney(item.amount)]);
      }
      return rows;
    }
    var source = data && data.result && typeof data.result === "object" ? data.result : data;
    if (source && typeof source === "object") {
      for (var key in source) {
        if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
        if (typeof source[key] === "number") rows.push([key, formatMoney(source[key])]);
      }
    }
    return rows;
  }

  function coverageNotes(data) {
    // Surface load-bearing "not covered/modeled" caveats next to the rows.
    var notes = [];
    var assumptions = data && data.assumptions;
    if (!Array.isArray(assumptions)) return notes;
    for (var i = 0; i < assumptions.length; i++) {
      var text = String(assumptions[i] || "");
      if (/not covered|not modeled|不支持|未覆盖/i.test(text)) notes.push(text);
    }
    return notes.slice(0, 3);
  }

  function skillDetailHtml(answer) {
    if (!answer || answer.type !== "skill_result") return "";
    var data = answer.data || {};
    if (data.status && data.status !== "ok") return "";
    var parts = [];
    var rows = skillRows(data);
    for (var i = 0; i < rows.length; i++) {
      parts.push(escapeHtml(rows[i][0]) + ' <span class="cp-cite">' + escapeHtml(rows[i][1]) + "</span>");
    }
    var html = parts.length ? "<br>" + parts.join("<br>") : "";
    var year = data.input && data.input.tax_year;
    if (year) {
      html += '<br><span style="font-size:10px;color:var(--ink4)">计税年度 ' + escapeHtml(String(year)) + "</span>";
    }
    var notes = coverageNotes(data);
    for (var j = 0; j < notes.length; j++) {
      html += '<br><span style="font-size:10px;color:var(--ink4)">※ ' + escapeHtml(notes[j]) + "</span>";
    }
    return html;
  }

  function structuredHtml(answer) {
    return renderMarkdownEscaped(describeAnswer(answer) || "（无内容）") + skillDetailHtml(answer);
  }

  function sourcesHtml(sources) {
    if (!sources || !sources.length) return "";
    var labels = [];
    for (var i = 0; i < Math.min(sources.length, 4); i++) {
      labels.push("<b>" + escapeHtml(String(sources[i])) + "</b>");
    }
    return '<div class="cp-src">⚡ 来源 · ' + labels.join(" · ") + "</div>";
  }

  function factCheckHtml(factCheck) {
    if (!factCheck || factCheck.verdict !== "warn") return "";
    var issues = (factCheck.issues || []).join(", ");
    return '<div class="cp-src">⚠ 核查提示 · ' + escapeHtml(issues) + "</div>";
  }

  // ---------- SSE plumbing ----------

  function parseSseChunk(buffer, onEvent) {
    var events = buffer.split("\n\n");
    var leftover = events.pop();
    for (var i = 0; i < events.length; i++) {
      var lines = events[i].split("\n");
      var name = "";
      var data = "";
      for (var j = 0; j < lines.length; j++) {
        if (lines[j].indexOf("event: ") === 0) name = lines[j].slice(7);
        else if (lines[j].indexOf("data: ") === 0) data = lines[j].slice(6);
      }
      if (name) {
        var parsed = null;
        try { parsed = JSON.parse(data); } catch (e) { parsed = null; }
        onEvent(name, parsed);
      }
    }
    return leftover;
  }

  function createAiBubble() {
    var container = document.getElementById("cpMsgs");
    var msg = document.createElement("div");
    msg.className = "cp-msg";
    var av = document.createElement("div");
    av.className = "cpav cpav-ai";
    av.textContent = "✦";
    var bub = document.createElement("div");
    bub.className = "cp-bub bai";
    msg.appendChild(av);
    msg.appendChild(bub);
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return bub;
  }

  /* ask(query, hooks):
       hooks.removeTyping() — clear the typing indicator
       hooks.onUnavailable() — backend unreachable AND nothing rendered yet;
                               caller decides the (clearly labelled) fallback
       hooks.onDone(plainText) — final plain text for chat history */
  function ask(query, hooks) {
    var state = {
      text: "",
      answer: null,
      sources: [],
      factCheck: null,
      bubble: null,
      eventCount: 0,
      finished: false,
    };

    function bubble() {
      if (!state.bubble) {
        hooks.removeTyping();
        state.bubble = createAiBubble();
      }
      return state.bubble;
    }

    function finish(interrupted) {
      if (state.finished) return;
      state.finished = true;
      var target = bubble();
      var html;
      if (state.text) {
        // Verified LLM text first, then the engine breakdown — the numbers
        // must always be on screen, never only "see details below".
        html = renderMarkdownEscaped(state.text) + skillDetailHtml(state.answer);
      } else {
        html = structuredHtml(state.answer);
      }
      if (interrupted) {
        html += '<br><span style="font-size:10px;color:var(--ink4)">⚠ 连接中断，以上内容可能不完整</span>';
      }
      target.innerHTML = html + sourcesHtml(state.sources) + factCheckHtml(state.factCheck);
      var container = document.getElementById("cpMsgs");
      container.scrollTop = container.scrollHeight;
      if (hooks.onDone) hooks.onDone(state.text || describeAnswer(state.answer));
    }

    function fail() {
      if (state.finished) return;
      if (state.eventCount > 0) {
        // Something already rendered — finalize honestly instead of
        // appending a contradictory offline answer below it.
        finish(true);
        return;
      }
      state.finished = true;
      hooks.removeTyping();
      if (hooks.onUnavailable) hooks.onUnavailable();
    }

    function httpError(status, message) {
      if (state.finished) return;
      state.finished = true;
      hooks.removeTyping();
      var target = createAiBubble();
      target.innerHTML = renderMarkdownEscaped(
        "后端返回错误（" + status + "）：" + (message || "请求未能完成，请调整问题后重试。")
      );
    }

    function onEvent(name, data) {
      state.eventCount += 1;
      if (name === "meta" && data) {
        state.sources = data.sources || [];
        state.factCheck = data.fact_check || null;
      } else if (name === "answer" && data) {
        state.answer = data;
      } else if (name === "text" && data && typeof data.delta === "string") {
        state.text += data.delta;
        bubble().innerHTML = renderMarkdownEscaped(state.text);
        var container = document.getElementById("cpMsgs");
        container.scrollTop = container.scrollHeight;
      } else if (name === "done") {
        finish(false);
      }
    }

    window.fetch(API_BASE_URL + "/api/assistant/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return null; }).then(function (body) {
          var detail = body && body.error && body.error.message;
          httpError(response.status, detail);
          return null;
        });
      }
      if (!response.body) {
        fail();
        return null;
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) {
            // Stream closed without a "done" event → finalize what we have.
            if (!state.finished) {
              if (state.eventCount > 0) finish(true);
              else fail();
            }
            return null;
          }
          buffer += decoder.decode(step.value, { stream: true });
          buffer = parseSseChunk(buffer, onEvent);
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      fail();
    });
  }

  window.TaxGlobalCopilot = {
    ask: ask,
    escapeHtml: escapeHtml,
  };
}());
