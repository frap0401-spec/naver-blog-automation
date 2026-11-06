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


def _wait(job) -> None:
    last = ""
    while job.task:
        if job.message != last:
            print("   ", job.message)
            last = job.message
        time.sleep(0.5)


def make(args) -> int:
    from . import pipeline, tts

    files = [(Path(p).name, Path(p).read_bytes()) for p in args.videos]
    job = pipeline.create(args.name, args.link)
    pipeline.add_files(job, files)
    print(f"[1/4] 올리기 완료 · 프로젝트 {job.id}")
    if args.script_file:
        text = Path(args.script_file).read_text(encoding="utf-8-sig")
        hook1 = hook2 = badge = ""
    else:
        pipeline.start_write(job, args.length, args.notes)
        _wait(job)
        if job.error:
            print("오류:", job.error)
            return 1
        scripts = job.analysis["scripts"]
        pick = scripts[min(max(1, args.script), len(scripts)) - 1]
        copy = pick["thumb_copies"][0] if pick["thumb_copies"] else {"line1": "", "line2": "", "badge": ""}
        text, hook1, hook2, badge = "\n".join(pick["lines"]), copy["line1"], copy["line2"], copy["badge"]
        print(f"[2/4] 원고 '{pick['style']}' 선택")
    pipeline.set_script(job, text, hook1, hook2, badge)
    pipeline.apply_settings(job, {"voice": args.voice or tts.default_voice(), "rate": args.rate, "bgm": args.bgm,
                                  "ratio": args.ratio, "style": args.style, "smart_cut": not args.no_smart_cut})
    pipeline.start_make(job)
    _wait(job)
    if job.status != "done" or job.error:
        print("오류:", job.error)
        return 1
    print(f"[3/4] 만들기 완료 ({job.duration:.1f}초, {job.elapsed:.0f}초 걸림)")
    for f in job.fixes:
        print("    컷 보정:", f)
    out = Path(args.out or ".").resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("shorts.mp4", "upload.txt", "subtitles.srt"):
        shutil.copy(job.dir / "out" / name, out / f"{job.id}_{name}")
    print(f"[4/4] 내보내기: {out}/{job.id}_shorts.mp4")
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
    m.add_argument("--notes", default="", help="추가 요청 (예: 자취하는 20대에게, 친근하게)")
    m.add_argument("--length", type=int, default=30, choices=[15, 30, 45], help="원고 길이(초)")
    m.add_argument("--ratio", default="9:16", choices=["9:16", "4:5", "1:1", "16:9"])
    m.add_argument("--style", default="insta", choices=["insta", "classic", "box", "minimal"])
    m.add_argument("--link", default="", help="쿠팡 파트너스 링크")
    m.add_argument("--script", type=int, default=1, help="고를 원고 번호(1~3)")
    m.add_argument("--script-file", default="", help="직접 쓴 원고 txt (AI 대신 사용)")
    m.add_argument("--voice", default="", help="예: edge:ko-KR-InJoonNeural:-10Hz 또는 el:<ElevenLabs voice_id>")
    m.add_argument("--rate", type=int, default=5, help="말 속도 %%")
    m.add_argument("--bgm", default="", help="assets/bgm 안의 파일명")
    m.add_argument("--no-smart-cut", action="store_true", help="어색한 컷 자동 보정 끄기")
    m.add_argument("--out", default="output")
    args = p.parse_args()
    if args.cmd == "make":
        sys.exit(make(args))
    serve(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8000), not getattr(args, "no_browser", False))


if __name__ == "__main__":
    main()
