"""ffmpeg 기반 영상/음성 처리: 길이 확인, 프레임 추출, 컷 생성, 합치기, 최종 렌더."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config


class MediaError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise MediaError("ffmpeg를 찾을 수 없습니다. ffmpeg를 설치하거나 `pip install imageio-ffmpeg`를 실행하세요.") from exc


def run(args: list[str], cwd: Path | None = None) -> str:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg 실패: {' '.join(args[:6])} ...\n{proc.stderr[-2000:]}")
    return proc.stderr


@dataclass
class ProbeInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: Path) -> ProbeInfo:
    """ffprobe 없이 `ffmpeg -i` 출력으로 길이와 해상도를 읽습니다."""
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = proc.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m and not re.search(r"Stream #.*Video:", out):
        raise MediaError(f"영상 길이를 읽을 수 없습니다: {path.name}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    width = height = 0
    vm = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", out)
    if vm:
        width, height = int(vm.group(1)), int(vm.group(2))
        # 세로 촬영 영상의 회전 메타데이터 반영
        if re.search(r"rotate\s*:\s*-?(90|270)", out) or re.search(r"rotation of -?90", out):
            width, height = height, width
    has_audio = bool(re.search(r"Stream #.*Audio:", out))
    return ProbeInfo(duration=duration, width=width, height=height, has_audio=has_audio)


def extract_frames(video: Path, out_dir: Path, every: float, prefix: str) -> list[tuple[float, Path]]:
    """`every`초 간격으로 프레임을 뽑아 (시각, 파일) 목록을 돌려줍니다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"{prefix}_%04d.jpg"
    run([
        "-i", str(video),
        "-vf", f"fps=1/{every:.3f},scale=512:-2",
        "-q:v", "4",
        str(pattern),
    ])
    frames = sorted(out_dir.glob(f"{prefix}_*.jpg"))
    # fps 필터는 각 구간의 가운데 근처 프레임을 뽑으므로 시각을 그에 맞춰 표시
    return [(round(i * every + every / 2, 1), f) for i, f in enumerate(frames)]


RATIOS = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def size_of(ratio: str) -> tuple[int, int]:
    return RATIOS.get(ratio, RATIOS["9:16"])


def _video_filter(info: ProbeInfo, w: int = 1080, h: int = 1920) -> str:
    """원하는 화면 비율(w x h)로 맞추는 필터. 비율이 많이 다르면 흐린 배경 위에 얹습니다."""
    z = config.ZOOM
    zw, zh = int(w * z) // 2 * 2, int(h * z) // 2 * 2
    src = (info.width / info.height) if info.height else w / h
    tgt = w / h
    common = f"setsar=1,fps={config.FPS},format=yuv420p"
    if tgt / 1.45 <= src <= tgt * 1.45:  # 비율이 비슷하면 꽉 채우기
        return f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={w}:{h},{common}"
    fw, fh = int(w * z) // 2 * 2, int(h * 0.94) // 2 * 2
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2,eq=brightness=-0.08[bgb];"
        f"[fg]scale={fw}:{fh}:force_original_aspect_ratio=decrease,crop=min(iw\\,{w}):min(ih\\,{h})[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{common}"
    )


def photo_to_video(img: Path, out: Path, seconds: float = 5.0) -> None:
    """사진을 천천히 확대되는 영상으로 만듭니다."""
    info = probe(img)
    iw, ih = max(2, info.width), max(2, info.height)
    scale = 1440 / max(iw, ih)
    ow, oh = int(iw * scale) // 2 * 2, int(ih * scale) // 2 * 2
    frames = int(seconds * config.FPS)
    run([
        "-loop", "1", "-i", str(img), "-t", f"{seconds:.2f}",
        "-vf", (f"scale={ow * 2}:{oh * 2},zoompan=z='min(zoom+0.0009,1.15)':d={frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={ow}x{oh}:fps={config.FPS},format=yuv420p"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out),
    ])


def filmstrip(src: Path, duration: float, out: Path, count: int = 16) -> None:
    """구간 고르기용 필름 띠(작은 장면 count개를 가로로 이은 이미지)."""
    every = max(0.1, duration / count)
    run([
        "-i", str(src), "-vf", f"fps=1/{every:.3f},scale=96:-2,crop=96:96,tile={count}x1",
        "-frames:v", "1", "-q:v", "5", str(out),
    ])


def cleanup_filter(info: ProbeInfo, cleanup: dict | None) -> str:
    """원본에 박힌 자막·워터마크 영역 처리 필터. 입력 [0:v] → 출력 [c].

    cleanup = {"mode": "crop" | "blur" | "erase", "box": [x, y, w, h]}  (0~1 비율 좌표)
    - crop : 그 영역이 있는 위/아래 띠를 잘라내고 나머지로 화면을 채움 (가장 깔끔)
    - blur : 그 영역만 강하게 흐림
    - erase: 주변 색으로 메워 지움 (작은 글자·로고에 적합)
    """
    mode = (cleanup or {}).get("mode", "")
    box = (cleanup or {}).get("box") or []
    if mode not in ("crop", "blur", "erase") or len(box) != 4 or not info.width or not info.height:
        return "[0:v]null[c]"
    x, y, w, h = (min(1.0, max(0.0, float(v))) for v in box)
    w, h = min(w, 1 - x), min(h, 1 - y)
    if w < 0.01 or h < 0.01:
        return "[0:v]null[c]"
    if mode == "crop":
        above, below = y, 1 - (y + h)
        if max(above, below) >= 0.4:
            if above >= below:
                return f"[0:v]crop=iw:trunc(ih*{above:.4f}/2)*2:0:0[c]"
            return f"[0:v]crop=iw:trunc(ih*{below:.4f}/2)*2:0:trunc(ih*{y + h:.4f}/2)*2[c]"
        mode = "blur"  # 가운데 영역은 잘라낼 수 없으니 흐림으로 대체
    W, H = info.width, info.height
    px, py = max(1, int(x * W)), max(1, int(y * H))
    pw, ph = max(4, min(int(w * W), W - px - 1)), max(4, min(int(h * H), H - py - 1))
    if mode == "erase":
        return f"[0:v]delogo=x={px}:y={py}:w={pw}:h={ph}[c]"
    r = max(4, min(pw, ph) // 6)
    return (
        f"[0:v]split=2[c0][c1];[c1]crop={pw}:{ph}:{px}:{py},boxblur={r}:4[cb];"
        f"[c0][cb]overlay={px}:{py}[c]"
    )


BEAUTY = {
    "none": "",
    "light": "bilateral=sigmaS=2:sigmaR=0.05,eq=brightness=0.02:saturation=1.04",
    "normal": "bilateral=sigmaS=4:sigmaR=0.08,eq=brightness=0.035:saturation=1.06:gamma=1.03",
    "strong": "bilateral=sigmaS=6:sigmaR=0.12,eq=brightness=0.05:saturation=1.08:gamma=1.05",
}


def frame_quantize(seconds: float) -> float:
    return math.ceil(seconds * config.FPS) / config.FPS


def make_segment(src: Path, info: ProbeInfo, start: float, duration: float, out: Path,
                 cleanup: dict | None = None, size: tuple[int, int] = (1080, 1920), beauty: str = "none") -> None:
    """원본에서 start부터 duration만큼 잘라 세로 컷을 만듭니다. 원본이 짧으면 반복합니다."""
    start = max(0.0, min(start, max(0.0, info.duration - 0.3)))
    remaining = info.duration - start
    args = []
    if remaining < duration:
        if info.duration >= duration:
            start = max(0.0, info.duration - duration - 0.05)
        else:
            args += ["-stream_loop", "-1"]
            start = 0.0
    args += [
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}", "-an",
        "-filter_complex", f"{cleanup_filter(info, cleanup)};[c]{_video_filter(_after_cleanup(info, cleanup), *size)}"
        f"{(',' + BEAUTY[beauty]) if BEAUTY.get(beauty) else ''}[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(config.FPS),
        str(out),
    ]
    run(args)


def _after_cleanup(info: ProbeInfo, cleanup: dict | None) -> ProbeInfo:
    """잘라내기 후의 화면 비율로 레이아웃(세로 채우기/흐린 배경)을 정합니다."""
    f = cleanup_filter(info, cleanup)
    m = re.search(r"crop=iw:trunc\(ih\*([\d.]+)/2\)", f)
    if not m:
        return info
    return ProbeInfo(info.duration, info.width, int(info.height * float(m.group(1))), info.has_audio)


def thumbnail(src: Path, t: float, out: Path) -> None:
    run(["-ss", f"{max(0.0, t):.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)])


def preview_frame(src: Path, info: ProbeInfo, t: float, cleanup: dict | None, out: Path,
                  size: tuple[int, int] = (1080, 1920)) -> None:
    """지우기 설정을 적용한 화면 한 장(미리보기)."""
    layout = _video_filter(_after_cleanup(info, cleanup), *size)
    run([
        "-ss", f"{max(0.0, t):.2f}", "-i", str(src), "-frames:v", "1",
        "-filter_complex", f"{cleanup_filter(info, cleanup)};[c]{layout}[l];[l]scale=360:-2[v]",
        "-map", "[v]", "-q:v", "4", str(out),
    ])


def segment_audio(src: Path, info: ProbeInfo, start: float, duration: float, out: Path, keep: bool) -> None:
    """컷 구간의 원래 소리(keep=False 이거나 소리가 없으면 무음)를 정확한 길이의 WAV로."""
    if keep and info.has_audio and info.duration > 0:
        start = max(0.0, min(start, max(0.0, info.duration - duration)))
        run(["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}", "-vn",
             "-af", f"apad,atrim=0:{duration:.3f}", "-ar", "44100", "-ac", "1", str(out)])
    else:
        run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{duration:.3f}", str(out)])


def to_wav(src: Path, out: Path, total: float) -> None:
    """음성을 44.1kHz 모노 WAV로 바꾸고 total초가 되도록 뒤에 무음을 붙입니다."""
    run([
        "-i", str(src),
        "-af", f"apad,atrim=0:{total:.3f}",
        "-ar", "44100", "-ac", "1", str(out),
    ])


def concat(files: list[Path], out: Path, copy: bool = True) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{f.name}'\n" for f in files), encoding="utf-8")
    args = ["-f", "concat", "-safe", "0", "-i", list_file.name]
    args += ["-c", "copy"] if copy else []
    args.append(out.name)
    run(args, cwd=out.parent)


def final_render(job_dir: Path, video: Path, narration: Path, ass: Path, out: Path, bgm: Path | None,
                 orig: Path | None = None, extras: list[tuple[Path, float]] | None = None) -> None:
    """컷 영상 + 나레이션 + (배경음악) + 자막을 합쳐 최종 mp4를 만듭니다."""
    fonts = ""
    if any(config.FONTS_DIR.glob("*.[ot]tf")) or any(config.FONTS_DIR.glob("*.ttc")):
        try:
            rel = os.path.relpath(config.FONTS_DIR, job_dir).replace("\\", "/")
            fonts = f":fontsdir={rel}"
        except ValueError:  # 다른 드라이브(Windows)
            fonts = ""
    args = ["-i", video.name, "-i", narration.name]
    mix, n = ["[1:a]"], 2
    pre = ""
    if orig:
        args += ["-i", orig.name]
        pre += f"[{n}:a]volume=0.7[o];"
        mix.append("[o]")
        n += 1
    for k, (ep, vol) in enumerate(extras or []):
        args += ["-i", ep.name if ep.parent == job_dir else str(ep)]
        pre += f"[{n}:a]volume={vol}[e{k}];"
        mix.append(f"[e{k}]")
        n += 1
    if bgm:
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        pre += f"[{n}:a]volume={config.BGM_VOLUME}[b];"
        mix.append("[b]")
    if len(mix) > 1:
        audio = f"{pre}{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]"
    else:
        audio = "[1:a]anull[a]"
    filt = f"[0:v]ass={ass.name}{fonts}[v];{audio}"
    args += [
        "-filter_complex", filt, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", "-shortest", out.name,
    ]
    run(args, cwd=job_dir)
