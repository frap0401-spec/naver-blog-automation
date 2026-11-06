/* 드롭컷 화면 */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const S = { cfg: null, job: null, poll: null, lines: [], dirty: false, wLen: 30, mode: "auto", pieces: [], tlZoom: 60, sel: -1 };
const API = (id, p = "") => `/api/projects/${id}${p}`;

async function api(url, opts = {}) {
  if (opts.json !== undefined) {
    opts = { ...opts, method: opts.method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts.json) };
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), err ? 6000 : 2400);
}
function seg(el, value) { $$("button", el).forEach((b) => b.classList.toggle("on", b.dataset.v === String(value))); }
function segVal(el) { const b = $("button.on", el); return b ? b.dataset.v : null; }
$$(".seg").forEach((el) => el.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && el.contains(b)) seg(el, b.dataset.v); }));
const fmt = (s) => { s = Math.max(0, s); const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`; };

/* ================= 라우팅 ================= */
function show(page) { ["home", "progress", "editor"].forEach((p) => ($("#" + p).hidden = p !== page)); window.scrollTo(0, 0); }
async function route() {
  clearTimeout(S.poll);
  const [kind, id] = location.hash.slice(1).split("/");
  if (id) {
    try { S.job = await api(API(id)); } catch { location.hash = ""; return; }
    if (S.job.task === "making" || S.job.task === "analyzing") return startProgress();
    if (kind === "e" && S.job.status === "done") return openEditor();
    openHome();
    if (S.job.task === "writing") pollWrite();
  } else {
    S.job = null;
    openHome();
  }
}
window.addEventListener("hashchange", route);

/* ================= 홈 ================= */
function openHome() {
  show("home");
  const j = S.job;
  if (j) S.mode = j.mode || "auto";
  applyMode();
  $("#btnNew").hidden = !j;
  $("#title").value = j?.title || "";
  $("#link").value = j?.link || "";
  $("#scriptText").value = (j?.script?.lines || []).map((l) => l.text).join("\n");
  $("#hook1").value = j?.script?.hook1 || "";
  $("#hook2").value = j?.script?.hook2 || "";
  $("#badge").value = j?.script?.badge || "";
  if (j) {
    seg($("#speed"), j.rate); seg($("#ratio"), j.ratio);
    $("#style").value = j.style; $("#bgm").value = j.bgm || ""; $("#smartCut").checked = j.smart_cut;
    seg($("#gTheme"), j.graphic_theme); seg($("#gPos"), j.graphic_pos); seg($("#gAmount"), j.graphic_amount);
    $("#sfxScene").value = j.sfx_scene || ""; $("#sfxGfx").value = j.sfx_graphic || ""; seg($("#beauty"), j.beauty);
    selectVoice(j.voice);
  }
  updateStylePrev();
  renderThumbs();
  loadProjects();
  updateMakeBtn();
}
$("#btnNew").onclick = () => { location.hash = ""; };

function renderThumbs(loading = 0) {
  const j = S.job;
  const src = j?.sources || [];
  $("#thumbs").innerHTML = src.map((s, i) => `
    <div class="thumb"><img src="${API(j.id, `/thumb/${i}`)}" alt="">
      <button class="x" data-i="${i}" title="빼기">✕</button>
      <span class="tag">${s.kind === "photo" ? "사진" : j.durations[i].toFixed(1) + "초"}</span></div>`).join("")
    + Array.from({ length: loading }, () => `<div class="thumb loading"><span class="spin"></span></div>`).join("");
  const nv = src.filter((s) => s.kind === "video").length, np = src.length - nv;
  $("#dropTitle").textContent = src.length ? `더 넣기 (영상 ${nv}개 · 사진 ${np}장)` : "영상·사진 넣기";
  $$("#thumbs .x").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault();
    try { S.job = await api(API(j.id, `/files/${b.dataset.i}`), { method: "DELETE" }); renderThumbs(); updateMakeBtn(); } catch (err) { toast(err.message, true); }
  }));
}

async function addFiles(list) {
  const files = [...list].filter((f) => /^(video|image)\//.test(f.type) || /\.(mp4|mov|m4v|webm|mkv|avi|jpe?g|png|webp)$/i.test(f.name));
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  renderThumbs(files.length);
  try {
    if (!S.job) {
      fd.append("title", $("#title").value); fd.append("link", $("#link").value); fd.append("mode", S.mode);
      S.job = await api("/api/projects", { method: "POST", body: fd });
      history.replaceState(null, "", "#p/" + S.job.id);
      $("#btnNew").hidden = false;
    } else {
      S.job = await api(API(S.job.id, "/files"), { method: "POST", body: fd });
    }
  } catch (err) { toast(err.message, true); }
  renderThumbs(); updateMakeBtn(); loadProjects();
}
const drop = $("#drop");
$("#files").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

function updateMakeBtn() { $("#btnMake").disabled = !(S.job?.sources?.length && (S.mode === "talk" || $("#scriptText").value.trim())); }
$("#scriptText").addEventListener("input", updateMakeBtn);

$("#btnPrompt").onclick = async () => {
  const text = S.cfg.chat_prompt.replace("{product}", $("#title").value || "(상품명)").replace("{notes}", "(특징)");
  await navigator.clipboard.writeText(text);
  toast("복사했어요. claude.ai 채팅에 붙여넣고, 나온 답을 원고 칸에 붙여넣으세요.");
};

function settings() {
  return {
    voice: $("#vVoice").value, rate: +segVal($("#speed")), ratio: segVal($("#ratio")), style: $("#style").value,
    bgm: $("#bgm").value, smart_cut: $("#smartCut").checked, title: $("#title").value.trim(), link: $("#link").value.trim(),
    graphic_theme: segVal($("#gTheme")), graphic_pos: segVal($("#gPos")), graphic_amount: segVal($("#gAmount")),
    sfx_scene: $("#sfxScene").value, sfx_graphic: $("#sfxGfx").value, beauty: segVal($("#beauty")),
  };
}
$("#btnMake").onclick = async () => {
  if (S.mode === "talk") {
    try {
      S.job = await api(API(S.job.id, "/talk"), { json: { level: segVal($("#cutLevel")), drop_fillers: $("#dropFillers").checked, settings: settings() } });
      history.replaceState(null, "", "#e/" + S.job.id);
      return startProgress();
    } catch (err) { return toast(err.message, true); }
  }
  try {
    S.job = await api(API(S.job.id, "/make"), { json: {
      script_text: $("#scriptText").value, hook1: $("#hook1").value.trim(), hook2: $("#hook2").value.trim(),
      badge: $("#badge").value.trim(), settings: settings(),
    } });
    history.replaceState(null, "", "#e/" + S.job.id);
    startProgress();
  } catch (err) { toast(err.message, true); }
};

/* 프로젝트 목록 */
async function loadProjects() {
  let list = [];
  try { list = await api("/api/projects"); } catch { return; }
  const g = $("#pgrid");
  if (!list.length) { g.innerHTML = '<p class="muted">아직 만든 프로젝트가 없어요.</p>'; return; }
  g.innerHTML = list.map((p) => `
    <div class="pcard" data-id="${p.id}" data-done="${p.status === "done"}">
      <div class="cv" style="background-image:url('${p.sources ? API(p.id, "/cover") + "?v=" + Math.round(p.duration * 10) : ""}')"></div>
      <div class="tags">${p.status === "done" ? '<span class="done">완성</span>' : p.task ? "<span>작업 중</span>" : "<span>편집 중</span>"}<span class="auto">${{ talk: "✂ 컷 편집", detail: "▤ 상세페이지" }[p.mode] || "✦ 자동 제작"}</span></div>
      <button class="del" title="지우기">✕</button>
      <div class="meta"><b>${esc(p.title)}</b><span class="muted small">${new Date(p.created * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" })}${p.duration ? " · " + p.duration.toFixed(0) + "초" : ""}</span></div>
    </div>`).join("");
  $$(".pcard", g).forEach((c) => {
    c.onclick = () => { location.hash = (c.dataset.done === "true" ? "#e/" : "#p/") + c.dataset.id; };
    $(".del", c).onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("이 프로젝트를 지울까요? 되돌릴 수 없어요.")) return;
      try { await api(API(c.dataset.id), { method: "DELETE" }); if (S.job?.id === c.dataset.id) location.hash = ""; loadProjects(); } catch (err) { toast(err.message, true); }
    };
  });
}

/* ================= 목소리 ================= */
const favs = () => { try { return JSON.parse(localStorage.getItem("dc_favs") || "[]"); } catch { return []; } };
const setFavs = (a) => { try { localStorage.setItem("dc_favs", JSON.stringify(a)); } catch {} };
function providers() {
  const ps = [...new Set(S.cfg.voices.map((v) => v.provider))];
  return ["★ 즐겨찾기", ...ps];
}
function fillVoices(keep) {
  const p = $("#vProvider").value;
  const list = p === "★ 즐겨찾기" ? S.cfg.voices.filter((v) => favs().includes(v.id)) : S.cfg.voices.filter((v) => v.provider === p);
  $("#vVoice").innerHTML = list.length ? list.map((v) => `<option value="${esc(v.id)}">${favs().includes(v.id) ? "★ " : ""}${esc(v.name)} · ${esc(v.desc)}</option>`).join("")
    : '<option value="">즐겨찾기한 목소리가 없어요</option>';
  if (keep && list.some((v) => v.id === keep)) $("#vVoice").value = keep;
  updateStar();
}
function selectVoice(id) {
  const v = S.cfg.voices.find((x) => x.id === id) || S.cfg.voices[0];
  $("#vProvider").value = v.provider; fillVoices(v.id);
}
function updateStar() { $("#vStar").textContent = favs().includes($("#vVoice").value) ? "★" : "☆"; }
$("#vProvider").onchange = () => fillVoices();
$("#vVoice").onchange = updateStar;
$("#vStar").onclick = () => {
  const id = $("#vVoice").value; if (!id) return;
  const f = favs(); setFavs(f.includes(id) ? f.filter((x) => x !== id) : [...f, id]);
  fillVoices(id);
};
const audio = new Audio();
$("#vPlay").onclick = async () => {
  const id = $("#vVoice").value; if (!id) return;
  $("#vPlay").textContent = "…";
  try {
    const res = await fetch(`/api/voices/${encodeURIComponent(id)}/preview?rate=${segVal($("#speed"))}`);
    if (!res.ok) throw new Error((await res.json()).detail);
    audio.src = URL.createObjectURL(await res.blob()); await audio.play();
  } catch (err) { toast("미리 듣기 실패: " + err.message, true); }
  $("#vPlay").textContent = "▶ 듣기";
};

/* 스타일 미리보기 */
function updateStylePrev() { $("#stylePrev").className = "style-prev " + $("#style").value; }
$("#style").onchange = updateStylePrev;

/* ================= 원고 쓰기 창 ================= */
$("#btnWrite").onclick = () => {
  if (!S.job?.sources?.length) return toast("영상이나 사진을 먼저 넣어 주세요.", true);
  $("#writeModal").hidden = false;
  if (S.job.analysis) renderDrafts(); else $("#wBody").innerHTML = "";
  $("#wGo").textContent = S.job.analysis ? "다시 쓰기" : "쓰기";
};
$("#wClose").onclick = () => ($("#writeModal").hidden = true);
$("#writeModal").addEventListener("click", (e) => { if (e.target.id === "writeModal") $("#writeModal").hidden = true; });
$("#wGo").onclick = async () => {
  try {
    S.job = await api(API(S.job.id, "/write"), { json: { length: +segVal($("#wLen")), request: $("#wReq").value, title: $("#title").value } });
    pollWrite();
  } catch (err) { toast(err.message, true); }
};
function pollWrite() {
  $("#wGo").disabled = true;
  $("#wBody").innerHTML = `<div class="writing"><span class="spin"></span><span id="wMsg">${esc(S.job.message || "쓰는 중")}</span></div>`;
  const tick = async () => {
    try { S.job = await api(API(S.job.id)); } catch { return; }
    if (S.job.task === "writing") { const m = $("#wMsg"); if (m) m.textContent = S.job.message; S.poll = setTimeout(tick, 1200); return; }
    $("#wGo").disabled = false;
    if (S.job.error) { $("#wBody").innerHTML = ""; return toast(S.job.error, true); }
    if (!$("#title").value && S.job.title) $("#title").value = S.job.title;
    $("#wGo").textContent = "다시 쓰기";
    renderDrafts();
  };
  tick();
}
function renderDrafts() {
  const a = S.job.analysis;
  const li = (arr) => `<ul>${(arr || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const rich = (t) => esc(t).replace(/\[([^\]]*)\]/g, "<em>$1</em>");
  $("#wBody").innerHTML = `
    <div class="ana"><div class="sum"><b>${esc(a.product_name)}</b> — ${esc(a.summary)}</div>
      <div><b>누가</b>${li(a.who)}</div><div><b>언제</b>${li(a.when)}</div><div><b>왜 사나</b>${li(a.why)}</div></div>
    <h3 style="margin-top:18px">원고 3안 <span class="muted small">썸네일 카피를 고르고 '이 원고로'를 누르면 원고 칸과 화면 문구에 들어가요</span></h3>
    <div class="drafts">${a.scripts.map((s, i) => `
      <div class="draft" data-i="${i}"><h4>${i + 1}안 · ${esc(s.style)}</h4>
        ${s.thumb_copies.map((c, k) => `<label class="tc"><input type="radio" name="tc${i}" value="${k}" ${k === 0 ? "checked" : ""}>
          <span>${c.badge ? `<span class="bd">${esc(c.badge)}</span><br>` : ""}${rich(c.line1)}<br>${rich(c.line2)}</span></label>`).join("")}
        <ol>${s.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ol>
        <button class="accent">이 원고로</button></div>`).join("")}</div>
    <div class="upl">
      <div class="box"><b>제목 후보</b>${(a.titles || []).map((t, i) => `${i + 1}. ${esc(t)}`).join("\n")}</div>
      <div class="box"><b>설명글</b>${esc(a.description)}</div>
      <div class="box"><b>답글</b>${esc(a.reply)}\n\n<b>DM 문구</b>${esc(a.dm)}</div>
      <div class="box"><b>검색어</b>${(a.keywords || []).map((k) => "#" + esc(k)).join(" ")}</div>
    </div>`;
  $$(".draft").forEach((d) => ($(".accent", d).onclick = () => {
    const s = a.scripts[+d.dataset.i];
    const c = s.thumb_copies[+$("input:checked", d).value] || {};
    $("#scriptText").value = s.lines.join("\n");
    $("#hook1").value = c.line1 || ""; $("#hook2").value = c.line2 || ""; $("#badge").value = c.badge || "";
    $("#writeModal").hidden = true; updateMakeBtn();
    $("#secScript").scrollIntoView({ behavior: "smooth" });
    toast("원고를 넣었어요. 목소리를 고르고 '만들기'를 누르세요.");
  }));
}

/* ================= 만드는 중 ================= */
function startProgress() {
  show("progress");
  $("#pgTitle").textContent = S.job.title || "새 프로젝트";
  const tick = async () => {
    try { S.job = await api(API(S.job.id)); } catch { S.poll = setTimeout(tick, 1500); return; }
    const j = S.job;
    const busy = j.task === "making" || j.task === "analyzing";
    $("#stages").innerHTML = (j.mode === "talk" ? S.cfg.talk_stages : S.cfg.stages).map((n, i) => {
      const c = !busy ? "done" : i < j.stage ? "done" : i === j.stage ? "on" : "";
      return `<li class="${c}"><span class="dot">${c === "done" ? "✓" : ""}</span>${i + 1}. ${esc(n)}</li>`;
    }).join("");
    $("#pgMsg").textContent = j.message || " ";
    $("#pgTime").textContent = `${Math.max(0, Math.round(Date.now() / 1000 - j.started))}초`;
    if (busy) { S.poll = setTimeout(tick, 1000); return; }
    if (j.status === "done" && !j.error) { location.hash = "#e/" + j.id; route(); }
    else { toast(j.error || "만들지 못했어요.", true); location.hash = "#p/" + j.id; route(); }
  };
  tick();
}

/* ================= 편집 ================= */
function openEditor() {
  show("editor");
  const j = S.job;
  S.lines = structuredClone(j.script.lines);
  setDirty(false);
  $("#eTitle").textContent = j.title || "제목 없음";
  $("#ev").src = API(j.id, `/files/video?v=${Math.round(j.elapsed * 10)}`);
  $("#player").style.maxWidth = { "9:16": "340px", "4:5": "380px", "1:1": "380px", "16:9": "380px" }[j.ratio];
  $("#eInfo").textContent = `${j.duration.toFixed(1)}초 · ${j.ratio} · ${j.elapsed ? Math.round(j.elapsed) + "초 만에 완성" : ""}`;
  $("#dlVideo").href = API(j.id, "/files/video?dl=1");
  $("#dlTxt").href = API(j.id, "/files/txt?dl=1");
  $("#dlSrt").href = API(j.id, "/files/srt?dl=1");
  $("#eFixes").hidden = !j.fixes.length;
  $("#eFixes").innerHTML = "✂ 어색한 컷을 자동으로 고쳤어요<br>" + j.fixes.map(esc).join("<br>");
  const talkMode = j.mode === "talk";
  $$(".talk-only").forEach((b) => (b.hidden = !talkMode));
  $$(".auto-only").forEach((b) => (b.hidden = talkMode));
  S.pieces = structuredClone(j.talk?.pieces || []);
  if (talkMode) renderPieces(); else { renderLines(); renderGfxLines(); renderSfxLines(); renderCleanups(); }
  seg($("#eTheme"), j.graphic_theme); seg($("#ePos"), j.graphic_pos); seg($("#eBeauty"), j.beauty);
  $("#eSfxScene").value = j.sfx_scene || ""; $("#eSfxGfx").value = j.sfx_graphic || "";
  fillCaption(); fillUpload();
  tab(talkMode ? "cuts" : "scenes");
  renderTimeline();
}
$("#eBack").onclick = () => { location.hash = ""; };
$("#eExport").onclick = (e) => { e.stopPropagation(); $("#eMenu").hidden = !$("#eMenu").hidden; };
document.addEventListener("click", () => ($("#eMenu").hidden = true));
function tab(t) {
  $$("#etabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  $$(".epane").forEach((p) => (p.hidden = p.id !== "t-" + t));
  if (S.job?.mode !== "talk") {
    if (t === "gfx") renderGfxLines();
    if (t === "sfx") renderSfxLines();
    if (t === "scenes") renderLines();
  }
}
$("#etabs").onclick = (e) => { const b = e.target.closest("button"); if (b) tab(b.dataset.t); };
function setDirty(v) { S.dirty = v; $("#eDirty").textContent = v ? "● 고친 내용이 아직 완성 영상에 없어요" : "저장됨 ✓"; if (v && $("#editor").hidden === false) renderTimeline(); }

const lineStart = (i) => (S.job.seg_lens || []).slice(0, i).reduce((a, b) => a + b, 0);
const lineLen = (i) => S.job.seg_lens?.[i] || Math.max(1.5, S.lines[i].text.replace(/\s/g, "").length * 0.17);
const srcName = (k) => { const s = S.job.sources[k]; return `${k + 1}. ${s.kind === "photo" ? "사진" : "영상"} · ${s.name}`; };

function renderLines() {
  const j = S.job;
  $("#lines").innerHTML = S.lines.map((ln, i) => {
    const part = lineLen(i) / Math.max(1, ln.clips.length);
    const cl = ln.clips[0] ? j.cleanup[String(ln.clips[0].v)] : null;
    return `
    <div class="line" data-i="${i}">
      <div class="num" title="이 장면으로 이동">${i + 1}</div>
      <div>
        <textarea class="lt" rows="1">${esc(ln.text)}</textarea>
        <div class="lm">${lineStart(i).toFixed(1)}초부터 · 목소리 ${lineLen(i).toFixed(1)}초</div>
        <div class="lb"><button class="ghost play">▶ 목소리 듣기</button><button class="ghost seek">▶ 이 장면 보기</button></div>
        ${ln.clips.map((c, k) => `
          <div class="clip" data-k="${k}">
            <span class="k">${k === 0 ? "영상" : "이어서 " + (k + 1)}</span>
            <div class="vsel"><select class="vs">${j.sources.map((s, v) => `<option value="${v}" ${v === c.v ? "selected" : ""}>${esc(srcName(v))}</option>`).join("")}</select>
              ${k > 0 ? '<button class="ghost x">✕ 빼기</button>' : ""}</div>
            <span class="k">쓰는 구간</span>
            <div><div class="strip" style="background-image:url('${API(j.id, `/strip/${c.v}`)}')"><div class="win"><i>${part.toFixed(1)}초</i></div></div>
              <div class="tm">${fmt(c.start)} ~ ${fmt(c.start + part)}</div></div>
          </div>`).join("")}
        ${ln.clips.length < 3 ? '<button class="ghost addclip">+ 영상 이어서</button> <span class="muted small">문장이 길면 영상 2개를 이어 붙여 줄 수 있어요</span>' : ""}
        <div class="opts">
          <label class="toggle"><input type="checkbox" class="oa" ${ln.orig_audio ? "checked" : ""}>원래 소리</label>
          <span>글자 가리기 <span class="chip ${cl ? "" : "off"}">${cl ? "가리는 중 · " + { crop: "확대해서 잘라내기", blur: "흐리게", erase: "주변색으로 지우기" }[cl.mode] : "안 가림"}</span></span>
        </div>
        ${ln.reason ? `<div class="why">Claude: ${esc(ln.reason)}</div>` : ""}
      </div>
      <div class="pv"><img src="${ln.clips[0] ? API(j.id, `/thumb/${ln.clips[0].v}?t=${(Math.round(ln.clips[0].start * 2) / 2).toFixed(1)}`) : ""}" alt=""></div>
    </div>`;
  }).join("");
  $$(".line").forEach(setupLine);
}

function setupLine(el) {
  const i = +el.dataset.i, ln = S.lines[i], j = S.job;
  const ta = $(".lt", el);
  const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
  grow(); ta.oninput = () => { ln.text = ta.value.replace(/\n/g, " "); grow(); setDirty(true); };
  const seek = () => { $$(".line").forEach((x) => x.classList.toggle("on", x === el)); const v = $("#ev"); v.currentTime = lineStart(i) + 0.05; v.play().catch(() => {}); };
  $(".num", el).onclick = seek; $(".seek", el).onclick = seek;
  $(".play", el).onclick = async () => {
    try {
      const res = await fetch(API(j.id, `/line/${i}/audio`));
      if (!res.ok) throw new Error((await res.json()).detail);
      audio.src = URL.createObjectURL(await res.blob()); await audio.play();
    } catch (err) { toast("듣기 실패: " + err.message, true); }
  };
  $(".oa", el).onchange = (e) => { ln.orig_audio = e.target.checked; setDirty(true); };
  $(".chip", el).onclick = () => tab("clean");
  const ac = $(".addclip", el);
  if (ac) ac.onclick = () => {
    const last = ln.clips[ln.clips.length - 1] || { v: 0, start: 0 };
    ln.clips.push({ v: (last.v + 1) % j.sources.length, start: 0 }); setDirty(true); renderLines();
  };
  $$(".clip", el).forEach((cel) => {
    const k = +cel.dataset.k, c = ln.clips[k];
    $(".vs", cel).onchange = (e) => { c.v = +e.target.value; c.start = 0; setDirty(true); renderLines(); };
    const x = $(".x", cel); if (x) x.onclick = () => { ln.clips.splice(k, 1); setDirty(true); renderLines(); };
    const strip = $(".strip", cel), win = $(".win", cel);
    const dur = j.durations[c.v], part = Math.min(dur, lineLen(i) / ln.clips.length);
    const place = () => {
      win.style.width = (part / dur) * 100 + "%";
      win.style.left = (c.start / dur) * 100 + "%";
      $(".tm", cel).textContent = `${fmt(c.start)} ~ ${fmt(c.start + part)}`;
    };
    place();
    let drag = null;
    const at = (e) => { const r = strip.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * dur; };
    strip.addEventListener("pointerdown", (e) => {
      strip.setPointerCapture(e.pointerId);
      const t = at(e);
      drag = e.target === win || win.contains(e.target) ? t - c.start : part / 2;
      c.start = Math.max(0, Math.min(dur - part, t - drag)); place();
    });
    strip.addEventListener("pointermove", (e) => { if (drag === null) return; c.start = Math.max(0, Math.min(dur - part, at(e) - drag)); place(); });
    strip.addEventListener("pointerup", () => {
      if (drag === null) return; drag = null; c.start = Math.round(c.start * 10) / 10; setDirty(true);
      if (k === 0) $(".pv img", el).src = API(j.id, `/thumb/${c.v}?t=${(Math.round(c.start * 2) / 2).toFixed(1)}`);
    });
  });
}

async function remake(extra = {}) {
  const j = S.job;
  try {
    S.job = await api(API(j.id, "/make"), { json: {
      hook1: j.script.hook1, hook2: j.script.hook2, badge: j.script.badge, settings: {},
      ...(j.mode === "talk" ? { pieces: S.pieces } : { lines: S.lines }), ...extra,
    } });
    startProgress();
  } catch (err) { toast(err.message, true); }
}
$("#eRemake").onclick = () => remake();
$("#eRechoose").onclick = () => { if (confirm("문장마다 장면을 Claude가 처음부터 다시 고를까요? 직접 바꾼 장면도 다시 골라져요.")) remake({ rechoose: true }); };

/* 자막·문구 탭 */
function fillCaption() {
  const j = S.job;
  $("#cBadge").value = j.script.badge || ""; $("#cHook1").value = j.script.hook1 || ""; $("#cHook2").value = j.script.hook2 || "";
  $("#cStyle").value = j.style; seg($("#cRatio"), j.ratio);
}
$("#cApply").onclick = () => remake({
  hook1: $("#cHook1").value.trim(), hook2: $("#cHook2").value.trim(), badge: $("#cBadge").value.trim(),
  settings: { style: $("#cStyle").value, ratio: segVal($("#cRatio")) },
});

/* 업로드 글 탭 */
function fillUpload() {
  const j = S.job, u = j.upload || {};
  const titles = j.analysis?.titles || [];
  $("#uTitleSel").innerHTML = '<option value="">제목 후보에서 고르기</option>' + titles.map((t) => `<option>${esc(t)}</option>`).join("");
  $("#uTitleSel").hidden = !titles.length;
  $("#uTitle").value = u.title || ""; $("#uDesc").value = u.description || ""; $("#uKeys").value = u.keywords || "";
  $("#uReply").value = u.reply || ""; $("#uDm").value = u.dm || "";
}
$("#uTitleSel").onchange = (e) => { if (e.target.value) $("#uTitle").value = e.target.value; };
const uploadData = () => ({ title: $("#uTitle").value, description: $("#uDesc").value, keywords: $("#uKeys").value, reply: $("#uReply").value, dm: $("#uDm").value });
$("#uSave").onclick = async () => {
  const j = S.job;
  try {
    S.job = await api(API(j.id, "/make"), { json: { hook1: j.script.hook1, hook2: j.script.hook2, badge: j.script.badge, upload: uploadData(), save_only: true } });
    toast("저장했어요.");
  } catch (err) { toast(err.message, true); }
};
$("#uCopyAll").onclick = async () => {
  await $("#uSave").onclick();
  const res = await fetch(API(S.job.id, "/files/txt"));
  await navigator.clipboard.writeText(await res.text());
  toast("제목·설명·답글·DM을 모두 복사했어요.");
};

/* 글자 가리기 탭 */
const CLEAN_MODES = [["", "안 가림"], ["crop", "확대해서 잘라내기 (가장 깔끔)"], ["blur", "흐리게"], ["erase", "주변색으로 지우기"]];
const PRESETS = { "아래 자막": [0.03, 0.74, 0.94, 0.18], "위 글자": [0.03, 0.04, 0.94, 0.16], "오른쪽 위 로고": [0.68, 0.02, 0.3, 0.1] };
function renderCleanups() {
  const j = S.job;
  S.cleanup = structuredClone(j.cleanup || {});
  S.thumbT = j.durations.map((d) => d / 2);
  $("#cleanups").innerHTML = j.sources.map((s, i) => `
    <div class="clean" data-i="${i}">
      <div><div class="muted small">${esc(srcName(i))} · 원본</div>
        <div class="pick"><img src="${API(j.id, `/thumb/${i}?t=${S.thumbT[i].toFixed(1)}`)}"><div class="box" hidden></div></div></div>
      <div><div class="muted small">결과</div><img class="after"></div>
      <div class="ctrl">
        <select class="cm">${CLEAN_MODES.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select>
        <div class="row">${Object.keys(PRESETS).map((k) => `<button class="ghost" data-p="${k}">${k}</button>`).join("")}</div>
        <div class="row"><button class="ghost other">다른 장면 보기</button></div>
      </div>
    </div>`).join("");
  $$(".clean").forEach(setupClean);
}
function setupClean(el) {
  const i = +el.dataset.i, key = String(i), j = S.job;
  const pick = $(".pick", el), boxEl = $(".box", el), sel = $(".cm", el);
  const cur = () => S.cleanup[key];
  const draw = () => {
    const c = cur(); sel.value = c ? c.mode : ""; boxEl.hidden = !c;
    if (c) Object.assign(boxEl.style, { left: c.box[0] * 100 + "%", top: c.box[1] * 100 + "%", width: c.box[2] * 100 + "%", height: c.box[3] * 100 + "%" });
  };
  let timer;
  const save = () => {
    draw(); clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const res = await api(API(j.id, "/cleanup"), { json: S.cleanup });
        S.job.cleanup = res.cleanup; setDirty(true); renderLines();
        $(".after", el).src = API(j.id, `/cleanpreview/${i}?t=${S.thumbT[i].toFixed(1)}&v=${Date.now()}`);
      } catch (err) { toast(err.message, true); }
    }, 350);
  };
  sel.onchange = () => { if (!sel.value) delete S.cleanup[key]; else S.cleanup[key] = { mode: sel.value, box: cur() ? cur().box : PRESETS["아래 자막"] }; save(); };
  $$("[data-p]", el).forEach((b) => (b.onclick = () => {
    S.cleanup[key] = { mode: cur() ? cur().mode : b.dataset.p === "오른쪽 위 로고" ? "blur" : "crop", box: PRESETS[b.dataset.p] }; save();
  }));
  $(".other", el).onclick = () => {
    const d = j.durations[i]; S.thumbT[i] = (S.thumbT[i] + d * 0.27) % d;
    $("img", pick).src = API(j.id, `/thumb/${i}?t=${S.thumbT[i].toFixed(1)}`); save();
  };
  let start = null;
  const pos = (e) => { const r = pick.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
  pick.addEventListener("pointerdown", (e) => { start = pos(e); pick.setPointerCapture(e.pointerId); });
  pick.addEventListener("pointermove", (e) => {
    if (!start) return; const p = pos(e);
    S.cleanup[key] = { mode: cur() ? cur().mode : "blur", box: [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.abs(p[0] - start[0]), Math.abs(p[1] - start[1])] };
    draw();
  });
  pick.addEventListener("pointerup", () => {
    if (!start) return; start = null; const c = cur();
    if (c && (c.box[2] < 0.02 || c.box[3] < 0.02)) delete S.cleanup[key];
    else if (c && c.box[2] > 0.5 && (c.box[1] + c.box[3] > 0.7 || c.box[1] < 0.3)) c.mode = sel.value || "crop";
    save();
  });
  draw();
  $(".after", el).src = API(j.id, `/cleanpreview/${i}?t=${S.thumbT[i].toFixed(1)}`);
}
$("#clApply").onclick = () => remake();

/* ================= 시작 ================= */
(async () => {
  S.cfg = await api("/api/config");
  $("#aiState").textContent = S.cfg.mock ? "테스트 모드" : S.cfg.ai ? "Claude 연결됨" : "Claude 키 없음 · 원고 직접 쓰기";
  $("#aiState").className = "pill" + (S.cfg.ai ? " ok" : "");
  $("#vProvider").innerHTML = providers().map((p) => `<option>${esc(p)}</option>`).join("");
  selectVoice(null);
  const have = new Set(S.cfg.voices.map((v) => v.provider));
  const missing = [["타입캐스트", "TYPECAST_API_KEY"], ["클로바 보이스", "NCP_CLOVA_CLIENT_ID·SECRET"], ["ElevenLabs", "ELEVENLABS_API_KEY"]]
    .filter(([n]) => !have.has(n)).map(([n, k]) => `${n}(${k})`);
  if (missing.length) $("#vHint").textContent += ` ${missing.join(", ")} 목소리는 .env에 키를 넣으면 나와요.`;
  const styles = S.cfg.styles.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  $("#style").innerHTML = styles; $("#cStyle").innerHTML = styles;
  $("#bgm").innerHTML = '<option value="">없음</option>' + S.cfg.bgm.map((b) => `<option>${esc(b)}</option>`).join("");
  const sfxOpts = '<option value="">없음</option>' + S.cfg.sfx.map((n) => `<option>${esc(n)}</option>`).join("");
  $$(".sfxsel").forEach((el) => (el.innerHTML = sfxOpts));
  route();
})();


/* ================= 모드 (컷·자막 / 자동 제작 / 상세페이지) ================= */
const MODE_HINT = {
  auto: "제품 영상 3~4개, 또는 사진 여러 장도 돼요. 사진은 천천히 움직이는 영상이 돼요 (mp4, mov, jpg, png)",
  detail: "쇼핑몰 상세페이지 이미지를 넣으세요. 길게 캡처한 이미지도 화면 크기로 잘라 장면으로 쓰고, Claude가 글을 읽어 원고를 써요 (jpg, png)",
  talk: "직접 찍은 말하는 영상을 넣으세요. 말 없는 부분을 잘라내고 받아쓴 자막을 붙여요 (mp4, mov)",
};
function applyMode() {
  $$("#modeTabs button").forEach((b) => b.classList.toggle("on", b.dataset.mode === S.mode));
  const talkMode = S.mode === "talk";
  ["#secScript", "#secVoice", "#secGfx", "#secSfx"].forEach((id) => ($(id).hidden = talkMode));
  $("#secTalk").hidden = !talkMode;
  $("#dropHint").textContent = MODE_HINT[S.mode];
  $("#files").accept = talkMode ? "video/*" : S.mode === "detail" ? "image/*" : "video/*,image/*";
  $("#btnMake").textContent = talkMode ? "자동 편집 시작" : "만들기";
  updateMakeBtn();
}
$("#modeTabs").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (S.job && S.job.mode !== b.dataset.mode) return toast("다른 방식은 '+ 새 프로젝트'에서 시작하세요.");
  S.mode = b.dataset.mode; applyMode();
};

/* 효과음 미리 듣기 */
document.addEventListener("click", async (e) => {
  const b = e.target.closest(".sfxplay"); if (!b) return;
  const name = $("#" + b.dataset.for)?.value || b.dataset.name; if (!name || name === "-") return;
  audio.src = `/api/sfx/${encodeURIComponent(name)}`; audio.play().catch(() => {});
});

/* ================= 편집: 컷 (말하는 영상) ================= */
function renderPieces() {
  const keep = S.pieces.filter((p) => p.keep), total = keep.reduce((a, p) => a + p.end - p.start, 0);
  const all = S.job.durations.reduce((a, b) => a + b, 0);
  $("#kSum").textContent = `원본 ${all.toFixed(1)}초 → ${total.toFixed(1)}초 (${(all - total).toFixed(1)}초 잘라냄)`;
  $("#pieces").innerHTML = S.pieces.map((p, i) => `
    <div class="piece ${p.keep ? "" : "off"}" data-i="${i}">
      <span class="tm">${S.job.sources.length > 1 ? "영상" + (p.v + 1) + " · " : ""}${fmt(p.start)} ~ ${fmt(p.end)}${p.note ? `<span class="nb">${esc(p.note)}</span>` : ""}</span>
      <input class="pt" value="${esc(p.text)}" placeholder="(받아쓴 말 없음)">
      <label class="toggle"><input type="checkbox" class="pk" ${p.keep ? "checked" : ""}>넣기</label>
    </div>`).join("");
  $$(".piece").forEach((el) => {
    const p = S.pieces[+el.dataset.i];
    $(".pt", el).oninput = (e) => { p.text = e.target.value; S.dirty = true; $("#eDirty").textContent = "● 고친 내용이 아직 완성 영상에 없어요"; };
    $(".pk", el).onchange = (e) => { p.keep = e.target.checked; setDirty(true); renderPieces(); };
  });
}
$("#kRemake").onclick = () => remake();

/* ================= 편집: 그래픽 ================= */
function renderGfxLines() {
  const types = S.cfg.graphic_types;
  $("#gfxLines").innerHTML = S.lines.map((ln, i) => {
    const g = ln.graphic || { type: "", title: "", items: [] };
    return `<div class="gl" data-i="${i}"><span class="num">${i + 1}</span><div>
      <div class="tx">${esc(ln.text)}</div>
      <div class="f"><select class="gt"><option value="">그래픽 없음</option>${Object.entries(types).map(([k, v]) => `<option value="${k}" ${g.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
        <input class="gti" placeholder="제목" value="${esc(g.title)}"><input class="gi" placeholder="항목 (쉼표로 나누기)" value="${esc((g.items || []).join(", "))}"></div>
    </div></div>`;
  }).join("");
  $$(".gl", $("#gfxLines")).forEach((el) => {
    const ln = S.lines[+el.dataset.i];
    const upd = () => {
      const type = $(".gt", el).value;
      ln.graphic = type ? { type, title: $(".gti", el).value.trim(), items: $(".gi", el).value.split(",").map((x) => x.trim()).filter(Boolean) } : null;
      if (ln.graphic && !ln.graphic.title && !ln.graphic.items.length) ln.graphic.title = ln.text.replace(/[.!?]+$/, "");
      setDirty(true);
    };
    $$("select, input", el).forEach((x) => (x.onchange = upd));
  });
}
$("#gApply").onclick = () => remake({ settings: { graphic_theme: segVal($("#eTheme")), graphic_pos: segVal($("#ePos")) } });

/* ================= 편집: 효과음 ================= */
function renderSfxLines() {
  const opts = (cur) => `<option value="" ${!cur ? "selected" : ""}>자동</option><option value="-" ${cur === "-" ? "selected" : ""}>없음</option>`
    + S.cfg.sfx.map((n) => `<option ${cur === n ? "selected" : ""}>${esc(n)}</option>`).join("");
  $("#sfxLines").innerHTML = S.lines.map((ln, i) => `<div class="gl" data-i="${i}"><span class="num">${i + 1}</span><div>
      <div class="tx">${esc(ln.text)}${ln.graphic ? ' <span class="muted small">· 그래픽 있음</span>' : ""}</div>
      <div class="f s"><select class="ls">${opts(ln.sfx || "")}</select><button class="ghost sm lp">▶</button></div></div></div>`).join("");
  $$(".gl", $("#sfxLines")).forEach((el) => {
    const ln = S.lines[+el.dataset.i];
    $(".ls", el).onchange = (e) => { ln.sfx = e.target.value; setDirty(true); };
    $(".lp", el).onclick = () => {
      let n = ln.sfx; if (!n) n = ln.graphic && $("#eSfxGfx").value ? $("#eSfxGfx").value : $("#eSfxScene").value;
      if (n && n !== "-") { audio.src = `/api/sfx/${encodeURIComponent(n)}`; audio.play().catch(() => {}); }
    };
  });
}
$("#sApply").onclick = () => remake({ settings: { sfx_scene: $("#eSfxScene").value, sfx_graphic: $("#eSfxGfx").value } });
$("#bApply").onclick = () => remake({ settings: { beauty: segVal($("#eBeauty")) } });

/* ================= 타임라인 ================= */
function tlModel() {
  const j = S.job;
  if (j.mode === "talk") {
    const offs = []; let o = 0;
    j.durations.forEach((d) => { offs.push(o); o += d; });
    return { talk: true, total: o, offs };
  }
  const lens = S.lines.map((_, i) => lineLen(i));
  const starts = lens.map((_, i) => lens.slice(0, i).reduce((a, b) => a + b, 0));
  return { talk: false, total: lens.reduce((a, b) => a + b, 0), lens, starts };
}
function outToSrc(t, m) { // 완성 영상 시각 → 원본 타임라인 시각 (말하는 영상)
  let acc = 0;
  for (const p of S.job.talk.pieces || []) {
    if (!p.keep) continue;
    const d = p.end - p.start;
    if (t <= acc + d) return m.offs[p.v] + p.start + (t - acc);
    acc += d;
  }
  return null;
}
function srcToOut(x, m) {
  let acc = 0;
  for (const p of S.job.talk.pieces || []) {
    if (!p.keep) continue;
    const a = m.offs[p.v] + p.start, b = m.offs[p.v] + p.end;
    if (x >= a && x <= b) return acc + (x - a);
    acc += b - a;
  }
  return null;
}
function renderTimeline() {
  const j = S.job, m = tlModel(), z = S.tlZoom;
  const W = Math.max(m.total * z, 200);
  const X = (t) => (t * z).toFixed(1) + "px";
  const step = z >= 80 ? 1 : z >= 30 ? 2 : 5;
  let html = `<div class="tl-ruler" style="width:${W}px">` + Array.from({ length: Math.floor(m.total / step) + 1 }, (_, k) => `<span style="left:${X(k * step)}">${fmt(k * step).replace(/\.\d$/, "")}</span>`).join("") + "</div>";
  if (m.talk) {
    $("#tlHint").textContent = "주황 = 들어가는 구간, 빗금 = 빠진 구간. 구간을 누르면 넣고 빼요. 구간 끝을 마우스로 끌면 늘리거나 줄일 수 있어요.";
    html += `<div class="tl-track big" style="width:${W}px"><span class="tl-label">영상</span>` + S.pieces.map((p, i) => {
      const a = m.offs[p.v] + p.start, w = (p.end - p.start) * z;
      return `<div class="tl-blk ${p.keep ? "keep" : "drop"}" data-i="${i}" style="left:${X(a)};width:${w}px" title="${esc(p.text)}"><span class="h l"></span>${esc(p.text || "")}<span class="h r"></span></div>`;
    }).join("") + "</div>";
  } else {
    $("#tlHint").textContent = "블록을 누르면 그 문장으로 가요. 위 카드에서 장면·그래픽·효과음을 바꿀 수 있어요.";
    const blk = (cls, i, txt, extra = "") => `<div class="tl-blk ${cls} ${i === S.sel ? "sel" : ""}" data-i="${i}" style="left:${X(m.starts[i])};width:${Math.max(4, m.lens[i] * z - 3)}px;${extra}">${txt}</div>`;
    html += `<div class="tl-track" style="width:${W}px"><span class="tl-label">그래픽</span>` + S.lines.map((ln, i) => ln.graphic ? blk("gfx", i, esc(ln.graphic.title || S.cfg.graphic_types[ln.graphic.type])) : "").join("") + "</div>";
    html += `<div class="tl-track" style="width:${W}px"><span class="tl-label">자막</span>` + S.lines.map((ln, i) => blk("sub", i, "T " + esc(ln.text))).join("") + "</div>";
    html += `<div class="tl-track big" style="width:${W}px"><span class="tl-label">영상</span>` + S.lines.map((ln, i) => {
      const c = ln.clips[0];
      return blk("vid", i, String(i + 1), c ? `background-image:url('${API(j.id, `/thumb/${c.v}?t=${(Math.round(c.start * 2) / 2).toFixed(1)}`)}')` : "");
    }).join("") + "</div>";
    const marks = [];
    S.lines.forEach((ln, i) => {
      let n = ln.sfx || "";
      if (n === "-") n = ""; else if (!n) n = ln.graphic && j.sfx_graphic ? j.sfx_graphic : i > 0 ? j.sfx_scene : "";
      if (n) marks.push(`<span class="tl-sfx" style="left:${X(m.starts[i])}" title="${esc(n)}">♪</span>`);
    });
    html += `<div class="tl-track" style="width:${W}px;height:22px"><span class="tl-label">효과음</span>${marks.join("")}</div>`;
  }
  html += `<div class="tl-head" id="tlHead"></div>`;
  $("#tlInner").innerHTML = html;
  $("#tlInner").style.width = W + 64 + "px";
  setupTimeline(m);
  movePlayhead();
}
function movePlayhead() {
  const v = $("#ev"), head = $("#tlHead"); if (!head || !S.job) return;
  const m = tlModel();
  const t = m.talk ? outToSrc(v.currentTime || 0, m) : v.currentTime || 0;
  head.style.left = 64 + (t ?? 0) * S.tlZoom + "px";
  $("#tlTime").textContent = `${fmt(v.currentTime || 0)} / ${fmt(S.job.duration || 0)}`;
}
$("#ev").addEventListener("timeupdate", movePlayhead);
$("#ev").addEventListener("play", function loop() { movePlayhead(); if (!$("#ev").paused) requestAnimationFrame(loop); });
$("#tlIn").onclick = () => { S.tlZoom = Math.min(240, S.tlZoom * 1.5); renderTimeline(); };
$("#tlOut").onclick = () => { S.tlZoom = Math.max(8, S.tlZoom / 1.5); renderTimeline(); };

function setupTimeline(m) {
  const inner = $("#tlInner"), z = S.tlZoom;
  const tAt = (e) => (e.clientX - inner.getBoundingClientRect().left - 64) / z;
  inner.onclick = (e) => {
    if (S._dragged) { S._dragged = false; return; }
    const b = e.target.closest(".tl-blk");
    const v = $("#ev");
    if (m.talk) {
      if (b && !e.target.classList.contains("h")) { const p = S.pieces[+b.dataset.i]; p.keep = !p.keep; setDirty(true); renderPieces(); return; }
      const o = srcToOut(tAt(e), m); if (o !== null) v.currentTime = o;
      return;
    }
    if (b) {
      const i = +b.dataset.i; S.sel = i; v.currentTime = m.starts[i] + 0.05;
      $$(".line").forEach((x) => x.classList.toggle("on", +x.dataset.i === i));
      const card = $(`.line[data-i="${i}"]`); if (card && !$("#t-scenes").hidden) card.scrollIntoView({ behavior: "smooth", block: "center" });
      renderTimeline();
    } else { const t = tAt(e); if (t >= 0) v.currentTime = Math.min(t, (S.job.duration || t)); }
  };
  if (!m.talk) return;
  $$(".tl-blk .h", inner).forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      e.stopPropagation(); h.setPointerCapture(e.pointerId);
      const blk = h.parentElement, i = +blk.dataset.i, p = S.pieces[i], left = h.classList.contains("l");
      const sameV = S.pieces.filter((q, k) => q.v === p.v && k !== i);
      const lo = Math.max(0, ...sameV.filter((q) => q.end <= p.start + 0.001).map((q) => q.end));
      const hi = Math.min(S.job.durations[p.v], ...sameV.filter((q) => q.start >= p.end - 0.001).map((q) => q.start));
      const move = (ev) => {
        const t = tAt(ev) - m.offs[p.v];
        if (left) p.start = Math.max(lo, Math.min(p.end - 0.15, t)); else p.end = Math.min(hi, Math.max(p.start + 0.15, t));
        blk.style.left = (m.offs[p.v] + p.start) * z + "px"; blk.style.width = (p.end - p.start) * z + "px";
      };
      const up = () => {
        h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up);
        p.start = Math.round(p.start * 100) / 100; p.end = Math.round(p.end * 100) / 100;
        S._dragged = true; setTimeout(() => (S._dragged = false), 50);
        setDirty(true); renderPieces();
      };
      h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
    });
  });
}
