#!/usr/bin/env bash
# Gate 2: record the real CDDA SDL/x11 UI under Xvfb and verify the clip is non-blank.
set -euo pipefail

# --- configuration ---
OUT="blitzy/evidence/cata-ui.mp4"
DISPLAY_NUM=99
GEOM="1920x1080"
FRAMERATE=30
RECORD_SECS=25
VCODEC="libx264"
PIXFMT="yuv420p"
# Minimum unique colors required in a frame extracted from the encoded MP4
# (H.264/yuv420p encoding spreads the palette across many values).
MIN_COLORS=500

mkdir -p "$(dirname "$OUT")"

# --- private scratch directory ---
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/cata-ui.XXXXXX")"
chmod 700 "$TMPROOT"
USERDIR="$TMPROOT/userdir/"
FRAME="$TMPROOT/frame.png"
BLACKLOG="$TMPROOT/blackdetect.log"
XVFB_LOG="$TMPROOT/xvfb.log"
GAME_LOG="$TMPROOT/game.log"
WARMUP_LOG="$TMPROOT/warmup.log"
XDG_DIR="$TMPROOT/xdg"
mkdir -p "$USERDIR" "$XDG_DIR"
chmod 700 "$XDG_DIR"

# --- process management ---
XVFB_PID=""
FFMPEG_PID=""
GAME_PID=""
WARMUP_PID=""
# shellcheck disable=SC2317
cleanup() {
    for pid in "$WARMUP_PID" "$GAME_PID" "$FFMPEG_PID" "$XVFB_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    if [ -n "${TMPROOT:-}" ] && [ -d "$TMPROOT" ]; then
        rm -rf "$TMPROOT" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

export DISPLAY=":${DISPLAY_NUM}"
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=dummy
export LIBGL_ALWAYS_SOFTWARE=1
export XDG_RUNTIME_DIR="$XDG_DIR"
# Force a uniform C locale: the game maps this to English and boots straight to
# the main menu, instead of stopping on the first-run "Select your language"
# modal (which never advances without input and leaves the capture blank).
export LC_ALL=C
unset LANG LANGUAGE 2>/dev/null || true

# --- preflight ---
if [ ! -x ./cataclysm-tiles ]; then
    echo "ERROR: ./cataclysm-tiles not found or not executable in $(pwd); build and Gate 1 must run first." >&2
    exit 1
fi

if command -v convert >/dev/null 2>&1; then
    IM=convert
elif command -v magick >/dev/null 2>&1; then
    IM=magick
else
    IM=""
fi

missing=0
for tool in Xvfb ffmpeg ffprobe; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: required tool '$tool' is not on PATH." >&2
        missing=1
    fi
done
if [ -z "$IM" ]; then
    echo "ERROR: ImageMagick ('convert' or 'magick') is not on PATH." >&2
    missing=1
fi
if [ "$missing" -ne 0 ]; then
    exit 1
fi

# --- start virtual framebuffer ---
Xvfb ":${DISPLAY_NUM}" -screen 0 "${GEOM}x24" >"$XVFB_LOG" 2>&1 &
XVFB_PID=$!
sleep 2
if command -v xdpyinfo >/dev/null 2>&1; then
    for _ in 1 2 3 4 5; do
        if xdpyinfo -display ":${DISPLAY_NUM}" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

# --- warm-up run ---
# A fresh user dir's first launch opens a minimum 80x24 window and only then
# writes the auto-detected terminal size to config; the recorded run below
# reuses this config so it opens at full resolution. Stop this run once the
# config file has been written.
./cataclysm-tiles --userdir "$USERDIR" >"$WARMUP_LOG" 2>&1 &
WARMUP_PID=$!
for _ in $(seq 1 40); do
    if [ -f "${USERDIR}config/options.json" ]; then
        break
    fi
    if ! kill -0 "$WARMUP_PID" 2>/dev/null; then
        break
    fi
    sleep 0.5
done
sleep 3
kill "$WARMUP_PID" 2>/dev/null || true
wait "$WARMUP_PID" 2>/dev/null || true
WARMUP_PID=""

# --- launch the recorded run and wait until the UI has actually rendered ---
# Starting the capture only after a non-blank frame appears keeps the clip free
# of the leading black frames produced while the game loads.
./cataclysm-tiles --userdir "$USERDIR" >"$GAME_LOG" 2>&1 &
GAME_PID=$!

ui_ready=0
for _ in $(seq 1 40); do
    sleep 1
    if ! kill -0 "$GAME_PID" 2>/dev/null; then
        echo "FAIL: cataclysm-tiles exited before the UI rendered." >&2
        cat "$GAME_LOG" >&2 2>/dev/null || true
        exit 1
    fi
    rm -f "$FRAME"
    ffmpeg -nostdin -y -loglevel error -f x11grab -video_size "$GEOM" \
        -i ":${DISPLAY_NUM}" -frames:v 1 "$FRAME" 2>/dev/null || true
    if [ -s "$FRAME" ]; then
        probe_colors="$("$IM" "$FRAME" -format "%k" info: 2>/dev/null || echo 0)"
        case "$probe_colors" in '' | *[!0-9]*) probe_colors=0 ;; esac
        if [ "$probe_colors" -ge 30 ]; then
            ui_ready=1
            break
        fi
    fi
done
if [ "$ui_ready" -ne 1 ]; then
    echo "FAIL: UI did not render a non-blank frame within the timeout; refusing to record a blank clip." >&2
    exit 1
fi
sleep 1

# --- record the live, already-rendered UI ---
ffmpeg -nostdin -y -loglevel error -f x11grab -video_size "$GEOM" -framerate "$FRAMERATE" \
    -i ":${DISPLAY_NUM}" -t "$RECORD_SECS" \
    -c:v "$VCODEC" -pix_fmt "$PIXFMT" "$OUT" &
FFMPEG_PID=$!

if ! wait "$FFMPEG_PID"; then
    echo "FAIL: ffmpeg recording process exited non-zero; the UI recording did not complete." >&2
    exit 1
fi
kill "$GAME_PID" 2>/dev/null || true
kill "$XVFB_PID" 2>/dev/null || true

# --- verify recording ---
if [ ! -s "$OUT" ]; then
    echo "FAIL: $OUT was not created or is empty." >&2
    exit 1
fi

echo "== Verifying $OUT rendered actual content =="

# (a) stream metadata
PROBE="$(ffprobe -v error -select_streams v:0 -count_frames \
    -show_entries stream=codec_name,width,height,nb_read_frames \
    -of default=noprint_wrappers=1 "$OUT" || true)"
printf '%s\n' "$PROBE"
CODEC="$(printf '%s\n' "$PROBE" | sed -n 's/^codec_name=//p')"
WIDTH="$(printf '%s\n' "$PROBE" | sed -n 's/^width=//p')"
HEIGHT="$(printf '%s\n' "$PROBE" | sed -n 's/^height=//p')"
NFRAMES="$(printf '%s\n' "$PROBE" | sed -n 's/^nb_read_frames=//p')"

if [ "$CODEC" != "h264" ]; then
    echo "FAIL: expected codec h264, got '${CODEC:-<none>}'." >&2
    exit 1
fi
if [ "$WIDTH" != "1920" ] || [ "$HEIGHT" != "1080" ]; then
    echo "FAIL: expected 1920x1080, got '${WIDTH:-?}x${HEIGHT:-?}'." >&2
    exit 1
fi
if ! [ "${NFRAMES:-0}" -gt 0 ] 2>/dev/null; then
    echo "FAIL: no frames decoded from $OUT (nb_read_frames='${NFRAMES:-}')." >&2
    exit 1
fi

# (b) reject a clip that is black from frame 0 (UI never rendered). The
# picture-black-ratio threshold classifies a frame as black only when almost
# all of its pixels are black.
if ! ffmpeg -nostdin -hide_banner -i "$OUT" -vf "blackdetect=d=1:pix_th=0.10:picture_black_ratio_th=0.995" -an -f null - >"$BLACKLOG" 2>&1; then
    cat "$BLACKLOG" >&2
    echo "FAIL: blackdetect verification could not run on $OUT." >&2
    exit 1
fi
if grep -Eq 'black_start:0([[:space:]]|$)' "$BLACKLOG"; then
    echo "FAIL: black_start:0 detected — clip is black from the first frame; UI never rendered (dummy driver? wrong DISPLAY?)." >&2
    exit 1
fi

# (c) unique-color content check on mid/late frames (highest wins)
COLORS=0
for t in 5 12 20; do
    rm -f "$FRAME"
    ffmpeg -nostdin -y -loglevel error -ss "$t" -i "$OUT" -frames:v 1 "$FRAME" 2>/dev/null || true
    if [ -s "$FRAME" ]; then
        c="$("$IM" "$FRAME" -format "%k" info: 2>/dev/null || echo 0)"
        case "$c" in '' | *[!0-9]*) c=0 ;; esac
        if [ "$c" -gt "$COLORS" ]; then
            COLORS="$c"
        fi
    fi
done
echo "mid-run frame unique colors: $COLORS"
if ! [ "$COLORS" -ge "$MIN_COLORS" ] 2>/dev/null; then
    echo "FAIL: only $COLORS unique colors (need >= $MIN_COLORS) — no real UI drew." >&2
    exit 1
fi

# --- verdict ---
echo "PASS"
echo "summary: codec=$CODEC resolution=${WIDTH}x${HEIGHT} frames=$NFRAMES unique_colors=$COLORS output=$OUT"
exit 0
