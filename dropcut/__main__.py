"""실행 방법
  웹 화면:   python -m dropcut                 (http://127.0.0.1:8000)
  자동 모드: python -m dropcut make 영상1.mp4 [영상2.mp4 ...] --name 상품명 --link 쿠팡링크
  직접 원고: python -m dropcut make 영상.mp4 --script-file 원고.txt   (API 키 불필요)
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import webbrowser
from pathlib import Path


def serve(host: str, port: int, open_browser: bool) -> None:
    import uvicorn

    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run("dropcut.server:app", host=host, port=port, log_level="warning")


def make(args) -> int:
    from . import pipeline, tts

    files = [(Path(p).name, Path(p).read_bytes()) for p in args.videos]
    script_text = Path(args.script_file).read_text(encoding="utf-8-sig") if args.script_file else ""
    mode = "manual" if script_text else "ai"
    job = pipeline.create(files, args.name, args.notes, args.link, mode, script_text)
    print(f"[1/5] 올리기 완료 · 작업 {job.id}")
    pipeline.start_analysis(job)
    while job.status == "analyzing":
        time.sleep(1)
    if job.status == "error":
        print("오류:", job.error)
        return 1
    scripts = job.analysis["scripts"]
    for i, s in enumerate(scripts):
        print(f"  원고 {i + 1} [{s['style']}] {s['hook_line1']} / {s['hook_line2']}")
    pick = min(max(1, args.script), len(scripts)) - 1
    pipeline.choose_script(job, scripts[pick])
    print(f"[2/5] 원고 {pick + 1} 선택")
    voice = args.voice or tts.default_voice()
    print(f"[3/5] 목소리 {voice} (속도 {args.rate:+d}%)")
    pipeline.start_render(job, voice, args.rate, args.bgm)
    last = ""
    while job.status == "rendering":
        if job.message != last:
            print("   ", job.message)
            last = job.message
        time.sleep(0.5)
    if job.status == "error":
        print("오류:", job.error)
        return 1
    print(f"[4/5] 만들기 완료 ({job.duration:.1f}초)")
    out = Path(args.out or ".").resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("shorts.mp4", "upload.txt", "subtitles.srt"):
        shutil.copy(job.dir / "out" / name, out / f"{job.id}_{name}")
    print(f"[5/5] 내보내기: {out}/{job.id}_shorts.mp4")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="dropcut", description="드롭컷 - 쇼핑쇼츠 자동 편집 에이전트")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="웹 화면 실행(기본)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--no-browser", action="store_true")
    m = sub.add_parser("make", help="한 번에 자동으로 만들기")
    m.add_argument("videos", nargs="+")
    m.add_argument("--name", default="", help="상품명")
    m.add_argument("--notes", default="", help="강조할 특징 메모")
    m.add_argument("--link", default="", help="쿠팡 파트너스 링크")
    m.add_argument("--script", type=int, default=1, help="고를 원고 번호(1~3)")
    m.add_argument("--script-file", default="", help="직접 쓴 원고 txt (AI 대신 사용)")
    m.add_argument("--voice", default="", help="예: edge:ko-KR-InJoonNeural:-10Hz 또는 el:<ElevenLabs voice_id>")
    m.add_argument("--rate", type=int, default=10, help="말 속도 %%")
    m.add_argument("--bgm", default="", help="assets/bgm 안의 파일명")
    m.add_argument("--out", default="output")
    args = p.parse_args()
    if args.cmd == "make":
        sys.exit(make(args))
    serve(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8000), not getattr(args, "no_browser", False))


if __name__ == "__main__":
    main()
