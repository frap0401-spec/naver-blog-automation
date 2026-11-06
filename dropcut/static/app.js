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
  $("#btnUpload").disabled = !state.files.length;
}
$("#files").onchange = (e) => setFiles(e.target.files);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => setFiles(e.dataTransfer.files));

$("#btnUpload").onclick = async () => {
  showError("");
  const fd = new FormData();
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
    $("#btnUpload").disabled = false;
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
    else { showStep(1); $("#btnUpload").disabled = !state.files.length; }
  }
}

/* ---------- 2. 원고 고르기 ---------- */
function renderScripts(job) {
  const a = job.analysis;
  $("#summary").textContent = `${a.product_name} — ${a.summary}`;
  $("#scripts").innerHTML = a.scripts.map((s, i) => `
    <div class="script ${i === state.scriptIdx ? "sel" : ""}" data-i="${i}">
      <div><span class="style">원고 ${i + 1} · ${esc(s.style)}</span></div>
      <div class="hook">
        <input class="h1" value="${esc(s.hook_line1)}" title="상단 제목 1줄">
        <input class="h2" value="${esc(s.hook_line2)}" title="상단 제목 2줄(강조)">
      </div>
      <ol>${s.lines.map((l) => `<li><textarea rows="2">${esc(l.text)}</textarea>
        <div class="cut">🎬 영상${l.video_index + 1} · ${l.start_sec.toFixed(1)}초 ${esc(l.visual)}</div></li>`).join("")}</ol>
      <div class="ttl">제목: ${esc(s.title)}</div>
    </div>`).join("");
  document.querySelectorAll(".script").forEach((el) => el.addEventListener("click", () => {
    state.scriptIdx = +el.dataset.i;
    document.querySelectorAll(".script").forEach((x) => x.classList.toggle("sel", x === el));
  }));
  $("#btnScript").disabled = false;
}

function collectScript() {
  const i = state.scriptIdx;
  const el = document.querySelector(`.script[data-i="${i}"]`);
  const s = structuredClone(state.job.analysis.scripts[i]);
  s.hook_line1 = el.querySelector(".h1").value.trim();
  s.hook_line2 = el.querySelector(".h2").value.trim();
  el.querySelectorAll("ol textarea").forEach((t, k) => { s.lines[k].text = t.value.trim(); });
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
  $("#voices").innerHTML = state.cfg.voices.map((v) => `
    <div class="voice ${v.id === state.voice ? "sel" : ""}" data-id="${v.id}">
      <div><b>${esc(v.name)}</b><div class="muted">${esc(v.desc)}</div></div>
      <button title="미리 듣기">▶</button>
    </div>`).join("");
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
        const res = await fetch(`/api/voices/${el.dataset.id}/preview?rate=${$("#rate").value}`);
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
  const id = location.hash.slice(1);
  if (id) {
    try { state.job = await api(`/api/jobs/${id}`); if (state.job.voice) state.voice = state.job.voice; renderVoices(); poll(); }
    catch { location.hash = ""; }
  }
})();
