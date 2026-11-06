/* 드롭컷 화면 */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const S = { cfg: null, job: null, poll: null, lines: [], dirty: false, wLen: 30 };
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
    if (S.job.task === "making") return startProgress();
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
      fd.append("title", $("#title").value); fd.append("link", $("#link").value);
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

function updateMakeBtn() { $("#btnMake").disabled = !(S.job?.sources?.length && $("#scriptText").value.trim()); }
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
  };
}
$("#btnMake").onclick = async () => {
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
      <div class="tags">${p.status === "done" ? '<span class="done">완성</span>' : p.task ? "<span>작업 중</span>" : "<span>편집 중</span>"}<span class="auto">✦ 자동 제작</span></div>
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
    $("#stages").innerHTML = S.cfg.stages.map((n, i) => {
      const c = j.task !== "making" ? "done" : i < j.stage ? "done" : i === j.stage ? "on" : "";
      return `<li class="${c}"><span class="dot">${c === "done" ? "✓" : ""}</span>${i + 1}. ${esc(n)}</li>`;
    }).join("");
    $("#pgMsg").textContent = j.message || " ";
    $("#pgTime").textContent = `${Math.max(0, Math.round(Date.now() / 1000 - j.started))}초`;
    if (j.task === "making") { S.poll = setTimeout(tick, 1000); return; }
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
  renderLines();
  fillCaption(); renderCleanups(); fillUpload();
  tab("scenes");
}
$("#eBack").onclick = () => { location.hash = ""; };
$("#eExport").onclick = (e) => { e.stopPropagation(); $("#eMenu").hidden = !$("#eMenu").hidden; };
document.addEventListener("click", () => ($("#eMenu").hidden = true));
function tab(t) { $$("#etabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t)); $$(".epane").forEach((p) => (p.hidden = p.id !== "t-" + t)); }
$("#etabs").onclick = (e) => { const b = e.target.closest("button"); if (b) tab(b.dataset.t); };
function setDirty(v) { S.dirty = v; $("#eDirty").textContent = v ? "● 고친 내용이 아직 완성 영상에 없어요" : "저장됨 ✓"; }

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
      hook1: j.script.hook1, hook2: j.script.hook2, badge: j.script.badge, lines: S.lines, settings: {}, ...extra,
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
  if (!S.cfg.eleven) $("#vHint").textContent += " ElevenLabs 목소리는 .env에 ELEVENLABS_API_KEY를 넣으면 나와요.";
  const styles = S.cfg.styles.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  $("#style").innerHTML = styles; $("#cStyle").innerHTML = styles;
  $("#bgm").innerHTML = '<option value="">없음</option>' + S.cfg.bgm.map((b) => `<option>${esc(b)}</option>`).join("");
  route();
})();
