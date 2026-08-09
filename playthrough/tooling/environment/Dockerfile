# ---------------------------------------------------------------------
# playthrough/tooling/environment/Dockerfile
#
# THE DECLARED PRODUCTION ENVIRONMENT for the playthrough capture and
# cinematography pipeline: a complete, capture-capable image on a Linux
# release that is IN SUPPORT.
#
# WHY THIS FILE EXISTS.  env.sh refuses to record a session on an
# end-of-life release, because ImageMagick, ffmpeg and the Xorg/Xvfb
# stack all parse untrusted-shaped input and an out-of-support archive
# publishes no fixes for them.  That refusal is correct and this file
# does not weaken it -- the escape hatch, PLAYTHROUGH_ALLOW_EOL_PLATFORM,
# is a registered trust bypass that moves the trust state to
# `diagnostic`, and under `diagnostic` launch_game.sh will not bring up
# an instance to be captured, capture.sh will not keep a frame,
# render_movie.py will not encode and embed_captions.sh will not mux.
#
# A code review then made the obvious point: a pipeline whose every
# production stage refuses on the only host available has no declared
# production path at all.  The host image supplied to this project is
# Ubuntu 25.10, which reached end of standard support on 2026-07-09, and
# the only supported-release container on it was an undeclared local
# image built from a file outside the repository that carried the media
# stack and nothing else -- no X server, no window manager, no xdotool,
# no SDL, no engine.  So the environment is DECLARED here, in the
# repository, buildable by anybody with this checkout, and complete
# enough to take a frame.
#
# WHAT "COMPLETE" MEANS, item by item, from env.sh's own toolchain
# assertion (playthrough_require_tools with no arguments):
#
#     Xvfb openbox xdpyinfo xwininfo xprop xdotool xauth
#     import convert identify ffmpeg ffprobe tesseract flock
#     setsid nohup grep awk sed
#
# plus the SDL2 runtime the engine links against, plus a Python
# interpreter holding exactly the pinned closure of requirements.lock,
# plus the compiler toolchain -- so the engine can be REBUILT in the
# same supported environment that captures it, rather than a binary
# built somewhere else being trusted to run here.
#
# THE BASE IS UBUNTU 26.04 LTS, for two reasons, and the second one was
# learned the hard way.
#
# FIRST, IT IS IN SUPPORT.  env.sh's dated support table
# (playthrough_check_platform) carries ubuntu:26.04 to 2031-04, so the
# platform gate passes on its own terms with no waiver and no trust
# bypass -- which is the whole point of this file.  It is also the
# migration target env.sh's own refusal message names.
#
# SECOND, 24.04 LTS CANNOT DRIVE THIS ENGINE'S MENUS, and this file was
# based on it until that was measured.  24.04 ships SDL2 2.30.0; on it
# every Dear ImGui screen -- which is the world creation dialog and,
# per the specification, the CHARACTER CREATOR -- renders correctly and
# then accepts no input at all.  Not a focus problem and not the
# renderer: with the Finish button visibly highlighted, `f`, `*`,
# Return, KP_Enter, Tab and a pixel-accurate mouse click on the button
# all did nothing, while the surrounding non-ImGui menu still answered
# `?` and Escape.  Rebuilding the engine inside 24.04 so that its
# compile-time and runtime SDL matched at 2.30.0 did NOT fix it.  On
# 26.04's SDL2 2.32.10 the same binary answers immediately: `*`
# randomises the world name and `f` raises the "Are you SURE you're
# finished?" confirmation.  So the SDL version is a FUNCTIONAL
# requirement of this pipeline, not a detail of the base image.
#
# THE ENGINE'S ABI FLOOR is comfortably cleared either way: the binary
# needs at most GLIBC_2.38 and GLIBCXX_3.4.32.
#
# SDL3 EXISTS HERE (libsdl3-dev 3.4.2) and satisfies the Makefile's
# `SDL3 >= 3.4.0` gate, but every build in this image passes SDL3=0
# deliberately: the SDL3 GPU shader path is out of scope for this
# feature, and the committed record was produced on the SDL2 fallback.
#
# THE COMPILER IS PINNED TO g++-14.  26.04's default is GCC 15, which
# does not build this engine under its own -Werror; 14 is the highest
# version the project documents as supported and is what every build
# here uses.
#
# APT VERSIONS ARE DELIBERATELY NOT PINNED, which is the opposite of the
# policy requirements.lock applies to the Python closure, and the reason
# is the same reason this file exists: the value of a supported release
# IS the security updates it publishes, and pinning the archive would
# freeze the image on the versions that were current the day it was
# written while telling everybody it was patched.  So the build takes
# the archive's current state and RECORDS it: the inventory below is
# written into the image, so what any given image actually contains is a
# fact it carries rather than a claim in a comment.
#
# BUILD AND USE IT THROUGH playthrough/tooling/supported_env.sh, which
# builds this file, mounts the checkout, refuses to forward a trust
# bypass into the container, and has a `preflight` subcommand that
# proves the declared path end to end.
# ---------------------------------------------------------------------

FROM ubuntu:26.04

# Every apt call in this file is non-interactive; a build that waited
# for a confirmation would hang rather than fail.
ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------
# The pipeline's own toolchain, the engine's runtime, and the compiler
# set that can rebuild the engine here.
#
# Grouped by what each group is FOR, because a flat list is unreviewable
# and the next person to change it needs to know what may not be dropped.
# ---------------------------------------------------------------------
RUN apt-get update \
 && apt-get -y upgrade \
 && apt-get -y install --no-install-recommends \
      `# The headless surface: an X server, a window manager so focus` \
      `# and keyboard delivery behave, the geometry probes env.sh uses` \
      `# to tell a missing tool from an absent server, xauth for the` \
      `# cookie that keeps the display authenticated, and the fallback` \
      `# capturer the pipeline's own helper names.` \
      xvfb openbox x11-utils x11-xserver-utils xauth scrot \
      `# Keystroke delivery, by window class.` \
      xdotool \
      `# Capture, preprocessing and inspection: import, convert and` \
      `# identify.  ImageMagick 7 in this archive provides them as` \
      `# alternatives, and the pipeline supports both 6 and 7.` \
      imagemagick \
      `# The encoder and the prober.` \
      ffmpeg \
      `# The sidebar clock reader, with the English data it needs.` \
      tesseract-ocr tesseract-ocr-eng \
      `# The engine's SDL2 runtime and fonts.  The committed binary` \
      `# links libSDL2, SDL2_ttf, SDL2_image, SDL2_mixer and` \
      `# libfreetype; fontconfig is what lets it find a face at all.` \
      libsdl2-2.0-0 libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 \
      libsdl2-mixer-2.0-0 libfreetype6 fontconfig \
      `# Rebuilding the engine in the SAME supported environment that` \
      `# captures it: GCC 14 is the highest version the project` \
      `# documents, and SDL3 is absent from this archive, so every make` \
      `# invocation carries SDL3=0 exactly as doc/c++/COMPILING.md` \
      `# anticipates.` \
      build-essential g++-14 make pkg-config ccache gettext \
      zlib1g-dev libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev \
      libsdl2-mixer-dev libfreetype-dev libncurses-dev \
      `# A system Python, which on this release is 3.14 and is` \
      `# therefore NOT the pipeline's interpreter -- the pipeline runs` \
      `# the CPython 3.12 built from source below, because that is the` \
      `# ABI requirements.lock pins wheels for.  This one is here` \
      `# because a Linux image without python3 surprises everything` \
      `# that assumes one, and because the CPython build itself wants a` \
      `# working interpreter available.` \
      python3 \
      `# The shell utilities the scripts assume: flock serialises the` \
      `# step lock, sha256sum attests each frame at publication, and a` \
      `# capture whose digest cannot be computed is withdrawn rather` \
      `# than recorded.` \
      coreutils util-linux findutils grep gawk sed bash \
      `# Reading the repository's own state, and fetching nothing else.` \
      git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------
# CPython 3.12, BUILT FROM SOURCE, because the interpreter version is
# part of this pipeline's contract and 26.04 does not carry it.
#
# env.sh pins PLAYTHROUGH_PYTHON_ABI="3.12" and refuses any other
# interpreter, for a reason it states itself: requirements.lock's wheels
# are cp312 and the lock is installed with --require-hashes and
# --only-binary :all:, so nothing can be built from source to paper over
# a mismatch.  26.04 ships Python 3.14 as `python3` and has no
# python3.12 package at all (apt-cache policy: empty candidate), so the
# choice is to build 3.12 here or to change the pinned closure -- and
# changing the closure to suit the base image would be the wrong way
# round, since the closure is what the rendered film's byte-level
# reproducibility rests on.
#
# THE TARBALL IS PINNED BY DIGEST.  The sha256 below was measured from
# https://www.python.org over TLS and is verified on every build; a
# mismatch fails the build rather than warning.  --enable-optimizations
# is deliberately NOT used: it triples the build for a speed-up this
# pipeline, which spends its time in ffmpeg and the engine, cannot
# notice.
ARG PYTHON_VERSION=3.12.13
ARG PYTHON_SHA256=0816c4761c97ecdb3f50a3924de0a93fd78cb63ee8e6c04201ddfaedca500b0b
RUN apt-get update \
 && apt-get -y install --no-install-recommends \
      curl ca-certificates libssl-dev libffi-dev libbz2-dev \
      liblzma-dev libsqlite3-dev libreadline-dev uuid-dev \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/python.tgz \
      "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" \
 && echo "${PYTHON_SHA256}  /tmp/python.tgz" | sha256sum -c - \
 && mkdir -p /tmp/python-src \
 && tar -xzf /tmp/python.tgz -C /tmp/python-src --strip-components=1 \
 && cd /tmp/python-src \
 && ./configure --prefix=/opt/python3.12 --with-ensurepip=install \
      --quiet \
 && make -j3 > /tmp/python-build.log 2>&1 \
 && make install > /tmp/python-install.log 2>&1 \
 && cd / && rm -rf /tmp/python-src /tmp/python.tgz \
 && /opt/python3.12/bin/python3.12 -V

# ---------------------------------------------------------------------
# The Python closure, installed from the hash-locked manifest and
# nothing else, into the 3.12 built above.
#
# requirements.lock sets --require-hashes and --only-binary :all: inside
# the file, so pip refuses any artifact whose sha256 is not listed and
# refuses to build anything from an sdist.  --no-deps is the lock's own
# documented invocation: the closure is complete, so resolution has
# nothing left to decide.
#
# /opt/playthrough-venv is the path env.sh finds through
# PLAYTHROUGH_VENV, and it is deliberately OUTSIDE the checkout -- a venv
# inside playthrough/ would land in the tree .gitignore re-includes
# wholesale, and env.sh refuses one there.
# ---------------------------------------------------------------------
COPY requirements.txt requirements.lock /opt/playthrough-requirements/
RUN /opt/python3.12/bin/python3.12 -m venv /opt/playthrough-venv \
 && /opt/playthrough-venv/bin/pip install --no-cache-dir \
      --upgrade pip setuptools wheel \
 && /opt/playthrough-venv/bin/pip install --no-cache-dir --no-deps \
      -r /opt/playthrough-requirements/requirements.lock \
 && /opt/playthrough-venv/bin/pip check
ENV PLAYTHROUGH_VENV=/opt/playthrough-venv

# ---------------------------------------------------------------------
# THE LINTER, because the acceptance gate will not run without one.
#
# verify_artifacts.sh asserts that the new Python satisfies the
# repository's own lint contract, and that check is DELIBERATELY NOT
# SKIPPABLE: a gate that quietly passed when its linter was missing would
# certify unlinted code as linted.  Without flake8 in this image the gate
# therefore FAILS HERE -- measured, as "no flake8 could be resolved" --
# which left the pipeline with no environment in which it could both
# legally render and pass its own gate.  That is the whole defect: not a
# missing convenience, a declared production environment that could not
# satisfy the acceptance criteria of the thing it was declared for.
#
# WHY APT AND NOT THE PINNED VENV.  Two reasons, and they point the same
# way.  First, /opt/playthrough-venv holds requirements.lock's closure
# installed with --require-hashes --only-binary :all: --no-deps; adding an
# unlisted package to it would make `pip check` and the closure's own
# integrity claim describe something other than what is installed, and the
# feature plan explicitly keeps flake8 out of requirements.txt as
# verification-only tooling rather than a runtime dependency of the
# pipeline.  Second, a checker is not a producer: the film's byte-level
# reproducibility rests on the render closure, and nothing flake8 does
# reaches an artifact.  So it is installed the way this file installs
# every other system tool, and for the reason stated at APT VERSIONS ARE
# DELIBERATELY NOT PINNED above.
#
# The archive's version here is the same upstream release the host's own
# lint environment carries, so the gate's verdict does not depend on which
# side of the container boundary it was measured from.  Whatever version a
# given build picks up is written into the inventory below, so the answer
# is a fact the image carries rather than a claim in this comment.
#
# This layer sits AFTER the interpreter and the closure so that changing
# it never rebuilds either -- the CPython compile is the expensive one --
# and BEFORE the inventory so that the inventory records it.
# ---------------------------------------------------------------------
RUN apt-get update \
 && apt-get -y install --no-install-recommends flake8 \
 && rm -rf /var/lib/apt/lists/* \
 && flake8 --version

# ---------------------------------------------------------------------
# What this image actually contains, recorded at build time.
#
# Not pinned, so measured: an image is only as trustworthy as the
# statement of what is in it, and this is that statement in a form
# `supported_env.sh inventory` can print and a report can quote.
# ---------------------------------------------------------------------
RUN { \
      echo "# playthrough supported capture environment"; \
      echo "# built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
      echo "# base:  $(. /etc/os-release; echo "${PRETTY_NAME}")"; \
      echo "# eol:   see env.sh playthrough_check_platform"; \
      echo; \
      echo "## apt"; \
      dpkg-query -W -f='${binary:Package}\t${Version}\n' \
        xvfb openbox x11-utils x11-xserver-utils xauth scrot xdotool \
        imagemagick ffmpeg tesseract-ocr tesseract-ocr-eng \
        libsdl2-2.0-0 libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 \
        libsdl2-mixer-2.0-0 libfreetype6 fontconfig \
        g++-14 make pkg-config ccache gettext zlib1g-dev \
        libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev \
        libsdl2-mixer-dev libfreetype-dev libncurses-dev \
        python3 coreutils util-linux git flake8 \
        | sort; \
      echo; \
      echo "## tools"; \
      for tool in Xvfb openbox xdpyinfo xwininfo xprop xdotool xauth \
                  import convert identify ffmpeg ffprobe tesseract \
                  flock setsid nohup flake8; do \
        printf '%s\t%s\n' "${tool}" "$(command -v "${tool}" \
          || echo MISSING)"; \
      done | sort; \
      echo; \
      echo "## python"; \
      echo "interpreter-source	python.org tarball, sha256 pinned"; \
      printf 'interpreter-built\t%s\n' \
        "$(/opt/python3.12/bin/python3.12 -V 2>&1)"; \
      printf 'interpreter-source-sha256\t%s\n' "${PYTHON_SHA256}"; \
      printf 'system-python3\t%s\n' "$(python3 -V 2>&1)"; \
      /opt/playthrough-venv/bin/python -V; \
      /opt/playthrough-venv/bin/pip list --format=freeze | sort; \
    } > /opt/playthrough-image-inventory.txt \
 && cat /opt/playthrough-image-inventory.txt

# A HOME that exists whatever uid the container is given.
#
# supported_env.sh runs the container as the HOST's uid so that files
# written into the mounted checkout belong to whoever will commit them --
# root-owned artifacts in somebody else's working tree are a repair job,
# not an artifact.  That uid has no passwd entry here, so HOME is pointed
# at a world-writable directory that is created now rather than assumed:
# openbox writes a session there, xauth writes the cookie's default
# location there, and both fail confusingly when it does not exist.
RUN mkdir -p /tmp/playthrough-home \
 && chmod 1777 /tmp/playthrough-home

# The checkout is BIND-MOUNTED at run time, never copied in: the record
# and the save data are the repository's, and an image carrying a copy of
# them would be a second, divergent copy of the evidence.
WORKDIR /workspace
CMD ["/bin/bash", "-l"]
