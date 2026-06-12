/* TaxGlobal AI — real W-2 photo upload + extraction (M3.6).
   Reads a local image, POSTs to /api/documents/extract-w2, renders the
   extracted boxes into the existing #w2Preview grid, and offers one-click
   fill into the calculator. The image is sent for THIS extraction only —
   never stored. All rendered values are HTML-escaped. */
(function () {
  var API_BASE_URL = "http://127.0.0.1:8000";
  var MAX_FILE_BYTES = 8 * 1024 * 1024;

  var BOX_LABELS = {
    box1: ["BOX 1", "工资及薪金"],
    box2: ["BOX 2", "联邦税代扣"],
    box3: ["BOX 3", "社保工资"],
    box4: ["BOX 4", "社保税代扣"],
    box5: ["BOX 5", "Medicare 工资"],
    box6: ["BOX 6", "Medicare 代扣"],
    box15_state: ["BOX 15", "州"],
    box16: ["BOX 16", "州工资"],
    box17: ["BOX 17", "州税代扣"],
  };

  function esc(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function money(value) {
    var amount = Number(value);
    if (!isFinite(amount)) return esc(value);
    return "$" + amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setProgress(label, pct) {
    var wrap = document.getElementById("progWrap");
    var labelEl = document.getElementById("progLabel");
    var pctEl = document.getElementById("progPct");
    var fill = document.getElementById("progFill");
    if (!wrap) return;
    wrap.classList.add("show");
    wrap.style.display = "block";
    if (labelEl) labelEl.textContent = label;
    if (pctEl) pctEl.textContent = pct + "%";
    if (fill) fill.style.width = pct + "%";
  }

  function hideProgress() {
    var wrap = document.getElementById("progWrap");
    // Clear the inline style instead of pinning display:none — the mock
    // demo path relies on the .show class working afterwards.
    if (wrap) { wrap.classList.remove("show"); wrap.style.display = ""; }
  }

  function renderFields(fields) {
    var preview = document.getElementById("w2Preview");
    var grid = preview ? preview.querySelector(".w2fg") : null;
    if (!preview || !grid) return;
    var html = "";
    var lowConfidence = [];
    for (var box in BOX_LABELS) {
      if (!Object.prototype.hasOwnProperty.call(BOX_LABELS, box)) continue;
      var field = fields[box] || {};
      var value = field.value;
      var display;
      if (value === null || typeof value === "undefined") {
        display = "—";
      } else if (box === "box15_state") {
        display = esc(value);
      } else {
        display = money(value);
      }
      if (value !== null && typeof value !== "undefined" && Number(field.confidence) < 0.8) {
        lowConfidence.push(BOX_LABELS[box][0]);
      }
      html += '<div class="w2f"><div class="wf-box">' + esc(BOX_LABELS[box][0]) + "</div>" +
        '<div class="wf-label">' + esc(BOX_LABELS[box][1]) + "</div>" +
        '<div class="wf-val">' + display + "</div></div>";
    }
    grid.innerHTML = html;

    // Replace the hardcoded demo footers with honest, dynamic ones.
    var notes = preview.querySelectorAll("[data-w2-note]");
    for (var i = 0; i < notes.length; i++) notes[i].remove();
    var note = document.createElement("div");
    note.setAttribute("data-w2-note", "1");
    note.setAttribute("style", "margin-top:10px;padding:9px 11px;background:var(--gbg);border-radius:8px;font-size:11px;color:var(--g)");
    note.textContent = "✓ 识别完成 — 请逐项核对后再填入计算器；图片未被存储。";
    preview.appendChild(note);
    if (lowConfidence.length) {
      var warn = document.createElement("div");
      warn.setAttribute("data-w2-note", "1");
      warn.setAttribute("style", "margin-top:8px;padding:9px 11px;background:var(--goldbg);border-radius:8px;font-size:11px;color:var(--gold)");
      warn.textContent = "⚠ 置信度较低，请人工核对: " + lowConfidence.join(", ");
      preview.appendChild(warn);
    }
    var fill = document.createElement("button");
    fill.setAttribute("data-w2-note", "1");
    fill.className = "btn pri";
    fill.setAttribute("style", "width:100%;margin-top:12px");
    fill.textContent = "填入税务计算器 →";
    fill.addEventListener("click", function () { fillCalculator(fields); });
    preview.appendChild(fill);

    preview.classList.add("show");
  }

  function fillCalculator(fields) {
    var wage = fields.box1 && fields.box1.value;
    var input = document.getElementById("tx-income");
    if (input && wage !== null && typeof wage !== "undefined") {
      input.value = wage;
      if (typeof input.oninput === "function") input.oninput();
    }
    var state = fields.box15_state && fields.box15_state.value;
    var stateSel = document.getElementById("tx-state");
    if (stateSel && state) {
      var hasOption = false;
      for (var i = 0; i < stateSel.options.length; i++) {
        if (stateSel.options[i].value === state) { hasOption = true; break; }
      }
      if (hasOption) {
        stateSel.value = state;
        if (typeof stateSel.onchange === "function") stateSel.onchange();
      }
      // Dropdown not yet populated (backend was down at page load) → wage
      // still fills; the user picks the state manually.
    }
    if (typeof window.go === "function") window.go("tax");
  }

  function showError(message) {
    hideProgress();
    var preview = document.getElementById("w2Preview");
    if (!preview) return;
    var notes = preview.querySelectorAll("[data-w2-note]");
    for (var i = 0; i < notes.length; i++) notes[i].remove();
    var note = document.createElement("div");
    note.setAttribute("data-w2-note", "1");
    note.setAttribute("style", "margin-top:10px;padding:9px 11px;background:var(--redbg);border-radius:8px;font-size:11px;color:var(--red)");
    note.textContent = message;
    preview.appendChild(note);
    preview.classList.add("show");
  }

  var busy = false;

  function extract(file) {
    if (!file || busy) return;
    if (file.size > MAX_FILE_BYTES) {
      showError("图片超过 8MB 上限，请压缩后重试。");
      return;
    }
    busy = true;
    function finishBusy() { busy = false; }
    setProgress("读取图片…", 15);
    var reader = new FileReader();
    reader.onerror = function () { showError("无法读取这个文件。"); finishBusy(); };
    reader.onload = function () {
      var dataUrl = String(reader.result || "");
      var comma = dataUrl.indexOf(",");
      var base64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
      var mediaType = file.type || "image/jpeg";
      setProgress("AI 识别中（图片不会被存储）…", 55);
      window.fetch(API_BASE_URL + "/api/documents/extract-w2", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_base64: base64, media_type: mediaType }),
      }).then(function (response) {
        return response.json().catch(function () { return null; }).then(function (body) {
          if (!response.ok) {
            var detail = body && body.error ? body.error : {};
            if (detail.code === "vision_unavailable") {
              showError("服务器未配置图像识别模型 — 可用下方「模拟上传演示」按钮，或前往税务计算页手动输入。");
            } else {
              showError("识别失败（" + (detail.code || response.status) + "）：" + (detail.message || "请重试。"));
            }
            finishBusy();
            return;
          }
          if (!body || !body.fields || typeof body.fields !== "object") {
            showError("服务器返回了空的识别结果，请重试。");
            finishBusy();
            return;
          }
          setProgress("完成", 100);
          window.setTimeout(hideProgress, 600);
          renderFields(body.fields);
          finishBusy();
        });
      }).catch(function () {
        showError("无法连接后端（127.0.0.1:8000）— 可用「模拟上传演示」按钮，或前往税务计算页手动输入。");
        finishBusy();
      });
    };
    reader.readAsDataURL(file);
  }

  var fileInput = null;

  function pickAndExtract() {
    if (!fileInput) {
      fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.accept = "image/jpeg,image/png,image/webp";
      fileInput.style.display = "none";
      fileInput.addEventListener("change", function () {
        if (fileInput.files && fileInput.files[0]) extract(fileInput.files[0]);
        fileInput.value = "";
      });
      document.body.appendChild(fileInput);
    }
    fileInput.click();
  }

  window.TaxGlobalW2 = {
    pickAndExtract: pickAndExtract,
  };
}());
