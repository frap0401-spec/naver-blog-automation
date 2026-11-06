const $ = (s) => document.querySelector(s);
const state = { files: [], job: null, scriptIdx: 0, voice: null, cfg: null, timer: null };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function showStep(n) {
  const visible = { 1: [1], 2: [2], 3: [2, 3], 4: [4], 5: [5] }[n];
  for (let i = 1; i <= 5; i++) $("#s" + i).hidden = !visible.includes(i);
  document.querySelectorAll("#steps li").forEach((li) => {
    const k = +li.dataset.step;
    li.className = k === n ? "on" : k < n ? "done" : "";
  });
  $("#s" + n).scrollIntoView({ behavior: "smooth", block: "start" });
}

function showError(msg, retry) {
  const box = $("#err");
  box.hidden = !msg;
  box.innerHTML = msg ? esc(msg) + (retry ? '<br><button id="btnRetry">다시 시도</button>' : "") : "";
  if (retry) $("#btnRetry").onclick = async () => { showError(""); await api(`/api/jobs/${state.job.id}/retry`, { method: "POST" }); poll(); };
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function setStatus(el, p, msg) {
  el.hidden = false;
  el.querySelector("i").style.width = Math.round(p * 100) + "%";
  el.querySelector("span").textContent = msg ? `${msg} · ${Math.round(p * 100)}%` : `${Math.round(p * 100)}%`;
}

/* ---------- 1. 올리기 ---------- */
const drop = $("#drop");
function setFiles(list) {
  state.files = [...list].filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(f.name));
  $("#filelist").innerHTML = state.files.map((f) => `<li>🎬 ${esc(f.name)} (${(f.size / 1048576).toFixed(1)}MB)</li>`).join("");
  updateMode();
}
$("#files").onchange = (e) => setFiles(e.target.files);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => setFiles(e.dataTransfer.files));

const mode = () => document.querySelector('input[name="mode"]:checked').value;
function updateMode() {
  const m = mode();
  $("#manualBox").hidden = m !== "manual";
  $("#btnUpload").textContent = m === "manual" ? "올리고 장면 배치하기" : "올리고 원고 만들기";
  $("#btnUpload").disabled = !state.files.length || (m === "manual" && !$("#scriptText").value.trim());
}
document.querySelectorAll('input[name="mode"]').forEach((r) => (r.onchange = updateMode));
$("#scriptText").oninput = updateMode;
$("#btnExample").onclick = () => { $("#scriptText").value = state.cfg.format_guide.replace(/\n\(나레이션[^)]*\)$/, ""); updateMode(); };
$("#btnPrompt").onclick = async (e) => {
  const text = state.cfg.chat_prompt.replace("{product}", $("#pname").value || "(상품명)").replace("{notes}", $("#pnotes").value || "(특징)");
  await navigator.clipboard.writeText(text);
  e.target.textContent = "복사됨! claude.ai에 붙여넣으세요";
  setTimeout(() => (e.target.textContent = "claude.ai용 요청문 복사"), 2000);
};

$("#btnUpload").onclick = async () => {
  showError("");
  const fd = new FormData();
  fd.append("mode", mode());
  fd.append("script_text", $("#scriptText").value);
  state.files.forEach((f) => fd.append("files", f));
  fd.append("product_name", $("#pname").value);
  fd.append("link", $("#plink").value);
  fd.append("notes", $("#pnotes").value);
  $("#btnUpload").disabled = true;
  setStatus($("#st1"), 0, "업로드 중");
  try {
    state.job = await api("/api/jobs", { method: "POST", body: fd });
    history.replaceState(null, "", "#" + state.job.id);
    poll();
  } catch (e) {
    showError(e.message);
    updateMode();
  }
};

/* ---------- 상태 폴링 ---------- */
function poll() {
  clearTimeout(state.timer);
  const tick = async () => {
    try {
      const job = await api(`/api/jobs/${state.job.id}`);
      state.job = job;
      render(job);
      if (job.status === "analyzing" || job.status === "rendering") state.timer = setTimeout(tick, 1200);
    } catch (e) { showError(e.message); }
  };
  tick();
}

function render(job) {
  if (job.status === "analyzing") { showStep(1); $("#btnUpload").disabled = true; setStatus($("#st1"), job.progress, job.message); }
  else if (job.status === "scripts_ready" && !job.chosen) { renderScripts(job); showStep(2); }
  else if (job.status === "scripts_ready" && job.chosen) { if (!$("#scripts").children.length) renderScripts(job); showStep(3); }
  else if (job.status === "rendering") { showStep(4); setStatus($("#st4"), job.progress, job.message); }
  else if (job.status === "done") renderDone(job);
  else if (job.status === "error") {
    showError("오류: " + job.error, true);
    if (job.analysis) { if (!$("#scripts").children.length) renderScripts(job); showStep(job.chosen ? 3 : 2); }
    else { showStep(1); updateMode(); }
  }
}

/* ---------- 2. 원고 고르기 ---------- */
function renderScripts(job) {
  const a = job.analysis;
  $("#summary").textContent = `${a.product_name} — ${a.summary}`;
  $("#scripts").classList.toggle("one", a.scripts.length === 1);
  $("#scripts").innerHTML = a.scripts.map((s, i) => `
    <div class="script ${i === state.scriptIdx ? "sel" : ""}" data-i="${i}">
      <div><span class="style">원고 ${i + 1} · ${esc(s.style)}</span></div>
      <div class="hook">
        <input class="h1" value="${esc(s.hook_line1)}" title="상단 제목 1줄">
        <input class="h2" value="${esc(s.hook_line2)}" title="상단 제목 2줄(강조)">
      </div>
      <ol>${s.lines.map((l) => `<li><textarea rows="2">${esc(l.text)}</textarea>
        <div class="cut">🎬 <select class="vi">${job.durations.map((d, k) => `<option value="${k}" ${k === l.video_index ? "selected" : ""}>영상${k + 1}</option>`).join("")}</select>
        <input class="ss" type="number" min="0" step="0.5" value="${l.start_sec.toFixed(1)}">초부터 ${esc(l.visual)}</div></li>`).join("")}</ol>
      <div class="ttl">제목: ${esc(s.title)}</div>
    </div>`).join("");
  document.querySelectorAll(".script").forEach((el) => el.addEventListener("click", () => {
    state.scriptIdx = +el.dataset.i;
    document.querySelectorAll(".script").forEach((x) => x.classList.toggle("sel", x === el));
  }));
  $("#btnScript").disabled = false;
  renderCleanups(job);
}

/* ---------- 원본 자막 지우기 ---------- */
const CLEAN_MODES = [["", "사용 안 함"], ["crop", "잘라내기 (가장 깔끔)"], ["blur", "흐리게"], ["erase", "주변색으로 지우기"]];
const PRESETS = { "아래 자막": [0.03, 0.74, 0.94, 0.18], "위 글자": [0.03, 0.04, 0.94, 0.16], "오른쪽 위 로고": [0.68, 0.02, 0.3, 0.1] };

function renderCleanups(job) {
  state.cleanup = structuredClone(job.cleanup || {});
  state.thumbT = job.durations.map((d) => d / 2);
  $("#cleanups").innerHTML = job.durations.map((d, i) => `
    <div class="clean" data-i="${i}">
      <div><div class="muted">영상${i + 1} 원본 (드래그로 영역 지정)</div>
        <div class="pick"><img src="/api/jobs/${job.id}/thumb/${i}?t=${state.thumbT[i].toFixed(1)}"><div class="box" hidden></div></div></div>
      <div><div class="muted">결과</div><img class="after"></div>
      <div class="ctrl">
        <label>방법 <select class="cm">${CLEAN_MODES.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></label>
        <div class="row">${Object.keys(PRESETS).map((k) => `<button type="button" data-p="${k}">${k}</button>`).join("")}</div>
        <div class="row"><button type="button" class="other">다른 장면 보기</button></div>
        <div class="muted hint"></div>
      </div>
    </div>`).join("");
  document.querySelectorAll(".clean").forEach(setupClean);
}

function setupClean(el) {
  const i = el.dataset.i, key = String(i);
  const pick = el.querySelector(".pick"), boxEl = el.querySelector(".box"), sel = el.querySelector(".cm");
  const cur = () => state.cleanup[key];
  const draw = () => {
    const c = cur();
    sel.value = c ? c.mode : "";
    boxEl.hidden = !c;
    if (c) Object.assign(boxEl.style, { left: c.box[0] * 100 + "%", top: c.box[1] * 100 + "%", width: c.box[2] * 100 + "%", height: c.box[3] * 100 + "%" });
    el.querySelector(".hint").textContent = c && c.mode === "crop" && c.box[1] > 0.3 && c.box[1] + c.box[3] < 0.7 ? "가운데 영역은 잘라낼 수 없어 흐리게 처리됩니다." : "";
  };
  let timer;
  const save = () => {
    draw();
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const job = await api(`/api/jobs/${state.job.id}/cleanup`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.cleanup) });
        state.job.cleanup = job.cleanup;
        el.querySelector(".after").src = `/api/jobs/${state.job.id}/cleanpreview/${i}?t=${state.thumbT[i].toFixed(1)}&v=${Date.now()}`;
      } catch (e) { showError(e.message); }
    }, 350);
  };
  sel.onchange = () => {
    if (!sel.value) delete state.cleanup[key];
    else state.cleanup[key] = { mode: sel.value, box: cur() ? cur().box : PRESETS["아래 자막"] };
    save();
  };
  el.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => {
    state.cleanup[key] = { mode: cur() ? cur().mode : b.dataset.p === "아래 자막" || b.dataset.p === "위 글자" ? "crop" : "blur", box: PRESETS[b.dataset.p] };
    save();
  }));
  el.querySelector(".other").onclick = () => {
    const d = state.job.durations[i];
    state.thumbT[i] = (state.thumbT[i] + d * 0.27) % d;
    pick.querySelector("img").src = `/api/jobs/${state.job.id}/thumb/${i}?t=${state.thumbT[i].toFixed(1)}`;
    save();
  };
  let start = null;
  const pos = (e) => { const r = pick.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
  pick.addEventListener("pointerdown", (e) => { start = pos(e); pick.setPointerCapture(e.pointerId); });
  pick.addEventListener("pointermove", (e) => {
    if (!start) return;
    const p = pos(e);
    const box = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.abs(p[0] - start[0]), Math.abs(p[1] - start[1])];
    state.cleanup[key] = { mode: cur() ? cur().mode : "blur", box };
    draw();
  });
  pick.addEventListener("pointerup", () => {
    if (!start) return;
    start = null;
    const c = cur();
    if (c && (c.box[2] < 0.02 || c.box[3] < 0.02)) delete state.cleanup[key];
    else if (c && c.box[2] > 0.5 && (c.box[1] + c.box[3] > 0.7 || c.box[1] < 0.3)) c.mode = sel.value || "crop";
    save();
  });
  draw();
  el.querySelector(".after").src = `/api/jobs/${state.job.id}/cleanpreview/${i}?t=${state.thumbT[i].toFixed(1)}`;
}

function collectScript() {
  const i = state.scriptIdx;
  const el = document.querySelector(`.script[data-i="${i}"]`);
  const s = structuredClone(state.job.analysis.scripts[i]);
  s.hook_line1 = el.querySelector(".h1").value.trim();
  s.hook_line2 = el.querySelector(".h2").value.trim();
  el.querySelectorAll("ol li").forEach((li, k) => {
    s.lines[k].text = li.querySelector("textarea").value.trim();
    s.lines[k].video_index = +li.querySelector(".vi").value;
    s.lines[k].start_sec = Math.max(0, +li.querySelector(".ss").value || 0);
  });
  return s;
}

$("#btnScript").onclick = async () => {
  showError("");
  try {
    state.job = await api(`/api/jobs/${state.job.id}/script`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectScript()),
    });
    showStep(3);
  } catch (e) { showError(e.message); }
};

/* ---------- 3. 목소리 고르기 ---------- */
const audio = new Audio();
function renderVoices() {
  const groups = {};
  state.cfg.voices.forEach((v) => (groups[v.provider] ||= []).push(v));
  let html = "";
  for (const [g, list] of Object.entries(groups)) {
    html += `<div class="vgroup">${esc(g)} <span class="muted">${list.length}명</span></div>`;
    html += list.map((v) => `
      <div class="voice ${v.id === state.voice ? "sel" : ""}" data-id="${esc(v.id)}">
        <div><b>${esc(v.name)}</b><div class="muted">${esc(v.desc)}</div></div>
        <button title="미리 듣기">▶</button>
      </div>`).join("");
  }
  if (!state.cfg.eleven) html += `<div class="vgroup muted">ElevenLabs 목소리를 쓰려면 .env 파일에 ELEVENLABS_API_KEY 를 넣고 다시 실행하세요.</div>`;
  $("#voices").innerHTML = html;
  document.querySelectorAll(".voice").forEach((el) => {
    el.addEventListener("click", () => {
      state.voice = el.dataset.id;
      document.querySelectorAll(".voice").forEach((x) => x.classList.toggle("sel", x === el));
      $("#btnRender").disabled = false;
    });
    el.querySelector("button").addEventListener("click", async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      btn.textContent = "…";
      try {
        const res = await fetch(`/api/voices/${encodeURIComponent(el.dataset.id)}/preview?rate=${$("#rate").value}`);
        if (!res.ok) throw new Error((await res.json()).detail);
        audio.src = URL.createObjectURL(await res.blob());
        await audio.play();
      } catch (err) { showError("미리 듣기 실패: " + err.message); }
      btn.textContent = "▶";
    });
  });
}
$("#rate").oninput = (e) => { const v = +e.target.value; $("#rateVal").textContent = (v >= 0 ? "+" : "") + v + "%"; };

$("#btnRender").onclick = async () => {
  showError("");
  try {
    state.job = await api(`/api/jobs/${state.job.id}/render`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice: state.voice, rate: +$("#rate").value, bgm: $("#bgm").value }),
    });
    showStep(4);
    poll();
  } catch (e) { showError(e.message); }
};

/* ---------- 5. 내보내기 ---------- */
function renderDone(job) {
  showStep(5);
  const base = `/api/jobs/${job.id}/files`;
  const v = `${base}/video?t=${Date.now()}`;
  if (!$("#preview").src.includes(base)) $("#preview").src = v;
  $("#dlVideo").href = `${base}/video?dl=1`;
  $("#dlTxt").href = `${base}/txt?dl=1`;
  $("#dlSrt").href = `${base}/srt?dl=1`;
  $("#exTitle").textContent = job.export.title;
  $("#exDesc").textContent = job.export.description;
  $("#exPin").textContent = job.export.pinned;
}
document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
  await navigator.clipboard.writeText($("#" + b.dataset.copy).textContent);
  b.textContent = "복사됨"; setTimeout(() => (b.textContent = "복사"), 1200);
}));
$("#btnBack").onclick = () => { $("#preview").pause(); $("#preview").removeAttribute("src"); showStep(3); };
$("#btnNew").onclick = () => { location.hash = ""; location.reload(); };

/* ---------- 시작 ---------- */
(async () => {
  state.cfg = await api("/api/config");
  state.voice = state.cfg.voices[0].id;
  renderVoices();
  $("#btnRender").disabled = false;
  $("#bgm").innerHTML = '<option value="">없음</option>' + state.cfg.bgm.map((b) => `<option>${esc(b)}</option>`).join("");
  if (state.cfg.llm === "mock") showError("테스트 모드(DROPCUT_LLM=mock): 실제 AI 대신 예시 원고가 나옵니다.");
  else if (!state.cfg.has_key) { document.querySelector('input[value="manual"]').checked = true; updateMode(); }
  const id = location.hash.slice(1);
  if (id) {
    try { state.job = await api(`/api/jobs/${id}`); if (state.job.voice) state.voice = state.job.voice; renderVoices(); poll(); }
    catch { location.hash = ""; }
  }
})();
