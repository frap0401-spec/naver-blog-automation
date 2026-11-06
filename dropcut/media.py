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
    if not m:
        raise MediaError(f"영상 길이를 읽을 수 없습니다: {path.name}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
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


def _video_filter(info: ProbeInfo) -> str:
    """1080x1920 세로 화면으로 맞추는 필터. 가로 영상은 흐린 배경 위에 얹습니다."""
    w, h, z = config.WIDTH, config.HEIGHT, config.ZOOM
    zw, zh = int(w * z) // 2 * 2, int(h * z) // 2 * 2
    aspect = (info.width / info.height) if info.height else 9 / 16
    if aspect <= 0.75:  # 세로 영상: 꽉 채우기
        return (
            f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={config.FPS},format=yuv420p"
        )
    # 가로/정사각 영상: 흐린 배경 + 가운데 원본
    fw = int(w * z) // 2 * 2
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2,eq=brightness=-0.08[bgb];"
        f"[fg]scale={fw}:-2,crop=min(iw\\,{w}):ih[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2-80,setsar=1,fps={config.FPS},format=yuv420p"
    )


def frame_quantize(seconds: float) -> float:
    return math.ceil(seconds * config.FPS) / config.FPS


def make_segment(src: Path, info: ProbeInfo, start: float, duration: float, out: Path) -> None:
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
        "-filter_complex", f"[0:v]{_video_filter(info)}[v]", "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(config.FPS),
        str(out),
    ]
    run(args)


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


def final_render(job_dir: Path, video: Path, narration: Path, ass: Path, out: Path, bgm: Path | None) -> None:
    """컷 영상 + 나레이션 + (배경음악) + 자막을 합쳐 최종 mp4를 만듭니다."""
    fonts = ""
    if any(config.FONTS_DIR.glob("*.[ot]tf")) or any(config.FONTS_DIR.glob("*.ttc")):
        try:
            rel = os.path.relpath(config.FONTS_DIR, job_dir).replace("\\", "/")
            fonts = f":fontsdir={rel}"
        except ValueError:  # 다른 드라이브(Windows)
            fonts = ""
    args = ["-i", video.name, "-i", narration.name]
    if bgm:
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        audio = (
            f"[2:a]volume={config.BGM_VOLUME}[b];"
            f"[1:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )
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
