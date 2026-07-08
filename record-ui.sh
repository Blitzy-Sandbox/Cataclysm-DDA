#!/usr/bin/env bash
# Gate 2: record the real CDDA SDL/x11 UI under Xvfb and verify the clip is non-blank.
#
# The game is rendered for real with the x11 video driver (never the zero-pixel dummy
# driver) into an Xvfb virtual framebuffer, under a minimal window manager (openbox) so
# keyboard input reaches the SDL window. The recorder drives the game to a brightly
# rendered, text-dense character-creation screen and only then starts capturing, so the
# resulting clip contains genuine UI from its first frame (no black_start:0) with many
# unique colors. The verification triad is unchanged: ffprobe stream metadata, a
# blackdetect check that rejects a clip that is black from frame 0, and an ImageMagick
# unique-color check that rejects a uniform (non-UI) fill.
set -euo pipefail

# --- configuration ---
OUT="blitzy/evidence/cata-ui.mp4"
DISPLAY_NUM=99
GEOM="1920x1080"
FRAMERATE=30
RECORD_SECS=25
VCODEC="libx264"
PIXFMT="yuv420p"
MIN_COLORS=50

mkdir -p "$(dirname "$OUT")"

# --- private scratch directory ---
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/cata-ui.XXXXXX")"
chmod 700 "$TMPROOT"
USERDIR="$TMPROOT/userdir/"
FRAME="$TMPROOT/frame.png"
BLACKLOG="$TMPROOT/blackdetect.log"
XVFB_LOG="$TMPROOT/xvfb.log"
WM_LOG="$TMPROOT/openbox.log"
GAME_LOG="$TMPROOT/game.log"
XDG_DIR="$TMPROOT/xdg"
mkdir -p "$USERDIR" "${USERDIR}config" "$XDG_DIR"
chmod 700 "$XDG_DIR"

# --- seed a windowed-borderless ASCII-tiles config so the window fills the framebuffer ---
# Without this, a fresh user directory boots to a tiny, near-black default window and the
# recording would be rejected as blank. These are stock CDDA option values (no rationale
# is embedded here per the Explainability rule; see blitzy/evidence/decision-log.md).
cat >"${USERDIR}config/options.json" <<'JSON'
[
  { "name": "USE_TILES", "value": "true" },
  { "name": "TILES", "value": "ASCIITiles" },
  { "name": "TERMINAL_X", "value": "128" },
  { "name": "TERMINAL_Y", "value": "48" },
  { "name": "FONT_WIDTH", "value": "8" },
  { "name": "FONT_HEIGHT", "value": "16" },
  { "name": "FONT_SIZE", "value": "16" },
  { "name": "FONT_BLENDING", "value": "false" },
  { "name": "SCALING_MODE", "value": "none" },
  { "name": "FULLSCREEN", "value": "windowedbl" },
  { "name": "SDL_KEYBOARD_MODE", "value": "keychar" }
]
JSON

# --- process management ---
XVFB_PID=""
WM_PID=""
FFMPEG_PID=""
GAME_PID=""
# shellcheck disable=SC2317
cleanup() {
    for pid in "$GAME_PID" "$FFMPEG_PID" "$WM_PID" "$XVFB_PID"; do
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
for tool in Xvfb ffmpeg ffprobe openbox xdotool; do
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

# --- start a minimal window manager so keyboard input reaches the SDL window ---
openbox >"$WM_LOG" 2>&1 &
WM_PID=$!
sleep 1

# --- launch the game (recording starts later, once a bright screen is up) ---
./cataclysm-tiles --userdir "$USERDIR" >"$GAME_LOG" 2>&1 &
GAME_PID=$!

# --- helpers ---
# Never fails the pipeline (returns empty until the window exists) so it is safe under
# `set -e`/`pipefail` while polling for the game window to appear.
game_window() { xdotool search --class Cataclysm 2>/dev/null | head -1 || true; }

send_keys() {
    local wid="$1"; shift
    xdotool windowactivate "$wid" >/dev/null 2>&1 || true
    xdotool windowfocus "$wid" >/dev/null 2>&1 || true
    local k
    for k in "$@"; do
        xdotool key --clearmodifiers "$k" >/dev/null 2>&1 || true
        sleep 0.6
    done
}

frame_colors() {
    rm -f "$FRAME"
    ffmpeg -nostdin -y -loglevel error -f x11grab -video_size "$GEOM" -i ":${DISPLAY_NUM}" \
        -frames:v 1 "$FRAME" >/dev/null 2>&1 || true
    if [ -s "$FRAME" ]; then
        local c
        c="$("$IM" "$FRAME" -format "%k" info: 2>/dev/null || echo 0)"
        case "$c" in '' | *[!0-9]*) c=0 ;; esac
        echo "$c"
    else
        echo 0
    fi
}

# --- wait for the game window, then drive to a bright character-creation screen ---
WID=""
for _ in $(seq 1 40); do
    WID="$(game_window)"
    if [ -n "$WID" ]; then
        break
    fi
    sleep 1
done
if [ -z "$WID" ]; then
    echo "FAIL: game window never appeared (see game log)." >&2
    cat "$GAME_LOG" >&2 || true
    exit 1
fi
sleep 3

# Dismiss the first-run language dialog, then: New Game -> Custom Character ->
# accept the default world (Finish, confirm) -> world generates (bright loading
# screen) -> character-creation tabs. Generous pauses absorb load time.
send_keys "$WID" Return                # select the highlighted language (English)
sleep 3
send_keys "$WID" Up Return             # main menu: choose "Custom Character"
sleep 3
send_keys "$WID" f                     # world-creation screen: Finish (accept defaults)
sleep 2
send_keys "$WID" Y                     # confirm "Are you SURE you're finished?" (case-sensitive)
sleep 8                                 # world mapgen + load (bright loading screen)

# Adaptive wait: only start recording once a grabbed frame is genuinely bright
# (>= MIN_COLORS unique colors), so the clip never starts on a black/near-black frame.
COLORS_PRE=0
for _ in $(seq 1 30); do
    COLORS_PRE="$(frame_colors)"
    if [ "${COLORS_PRE:-0}" -ge "$MIN_COLORS" ] 2>/dev/null; then
        break
    fi
    sleep 1
done
echo "pre-record bright-frame unique colors: ${COLORS_PRE}"

# --- record the UI ---
ffmpeg -nostdin -y -loglevel error -f x11grab -video_size "$GEOM" -framerate "$FRAMERATE" \
    -i ":${DISPLAY_NUM}" -t "$RECORD_SECS" \
    -c:v "$VCODEC" -pix_fmt "$PIXFMT" "$OUT" &
FFMPEG_PID=$!

# While recording, gently browse the character-creation list so the clip also shows the
# UI responding to input (kept on the bright creation screen; no world time elapses here).
sleep 2
send_keys "$WID" Down Down Down Up Up
sleep 3
send_keys "$WID" Down Down Up

if ! wait "$FFMPEG_PID"; then
    echo "FAIL: ffmpeg recording process exited non-zero; the UI recording did not complete." >&2
    exit 1
fi
kill "$GAME_PID" 2>/dev/null || true
kill "$WM_PID" 2>/dev/null || true
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

# (b) reject a clip that is black from frame 0 (UI never rendered)
if ! ffmpeg -nostdin -hide_banner -i "$OUT" -vf "blackdetect=d=1:pix_th=0.10" -an -f null - >"$BLACKLOG" 2>&1; then
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
