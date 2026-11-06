"""효과음: 기본 효과음은 ffmpeg로 직접 만들고, assets/sfx 에 넣은 파일도 함께 씁니다."""
from __future__ import annotations

from pathlib import Path

from . import config, media

SFX_DIR = config.ROOT / "assets" / "sfx"
BUILTIN_DIR = config.WORKSPACE / "_sfx"

BUILTIN = {
    "휙": "anoisesrc=d=0.45:c=pink:a=0.6,highpass=f=700,lowpass=f=6000,afade=t=in:d=0.18,afade=t=out:st=0.18:d=0.27",
    "뿅": "aevalsrc='0.5*sin(2*PI*(500+2200*t)*t)':d=0.16,afade=t=out:st=0.06:d=0.1",
    "띵": "aevalsrc='0.35*sin(2*PI*1318*t)*exp(-5*t)+0.2*sin(2*PI*2637*t)*exp(-7*t)':d=0.7",
    "딸깍": "aevalsrc='0.6*sin(2*PI*1800*t)*exp(-60*t)':d=0.06",
    "두둥": "aevalsrc='0.8*sin(2*PI*70*t)*exp(-6*t)':d=0.5,volume=1.4",
}
EXT = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}


def names() -> list[str]:
    custom = sorted(p.stem for p in SFX_DIR.glob("*") if p.suffix.lower() in EXT) if SFX_DIR.exists() else []
    return list(BUILTIN) + [c for c in custom if c not in BUILTIN]


def path(name: str) -> Path | None:
    if name in BUILTIN:
        out = BUILTIN_DIR / f"{list(BUILTIN).index(name)}.wav"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            media.run(["-f", "lavfi", "-i", BUILTIN[name], "-ar", "44100", "-ac", "1", str(out)])
        return out
    if SFX_DIR.exists():
        for p in SFX_DIR.iterdir():
            if p.stem == name and p.suffix.lower() in EXT:
                return p
    return None


def build_track(events: list[tuple[float, str]], total: float, out: Path, volume: float = 0.55) -> bool:
    """(시각, 효과음 이름) 목록으로 전체 길이의 효과음 트랙을 만듭니다. 없으면 False."""
    items = [(t, path(n)) for t, n in events if n]
    items = [(t, p) for t, p in items if p and 0 <= t < total]
    if not items:
        return False
    args = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
    parts = []
    for i, (t, p) in enumerate(items, 1):
        args += ["-i", str(p)]
        ms = int(t * 1000)
        parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,volume={volume},adelay={ms}:all=1[s{i}]")
    mix = "".join(f"[s{i}]" for i in range(1, len(items) + 1))
    fc = ";".join(parts) + f";[0:a]{mix}amix=inputs={len(items) + 1}:duration=first:dropout_transition=0:normalize=0[a]"
    args += ["-filter_complex", fc, "-map", "[a]", "-ar", "44100", "-ac", "1", str(out)]
    media.run(args)
    return True
