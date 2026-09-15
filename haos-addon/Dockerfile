# Real add-on Dockerfile shape, matching home-assistant/addons/configurator's
# real, currently-published Dockerfile (a Python add-on on the official
# Alpine-based base image) — not invented. See build.yaml for the pinned
# base image and this repo's README, "HAOS add-on packaging" section, for
# the exact reference this was built from.
#
# BUILD CONTEXT: the repo root (willo-ha/), not this directory — this
# add-on shares the `orchestrator/` Python package and the built
# `willo-claim-ui/dist/` with the rest of this repo rather than
# duplicating them, so it must be built with:
#   docker build -f haos-addon/Dockerfile -t willo-local .
# from the repo root (a deliberate deviation from the single-self-contained
# -folder convention most published add-ons use, since those don't share
# code with a sibling package the way this repo's orchestrator does — see
# the README for why this was the chosen tradeoff over duplicating the
# orchestrator source into this directory).
ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apk add --no-cache python3 py3-pip

# The orchestrator's own Python package — same code, same tests, as the
# plain-venv sandbox this repo's README documents testing against.
COPY orchestrator /opt/orchestrator
RUN pip3 install /opt/orchestrator \
    && find /usr/lib/python3* \
        \( -type d -a -name test -o -name tests -o -name __pycache__ \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

# Built at image-build time, per the original design (OxyHQ/Willo issue
# #9: "no Node runtime needed on the device itself") — `bun run build` in
# willo-claim-ui/ happens BEFORE this docker build, not inside it, so this
# image never needs Node/Bun at all.
COPY willo-claim-ui/dist /opt/willo-claim-ui-dist

# Copy S6 service definition + run script
COPY haos-addon/rootfs /

LABEL \
    org.opencontainers.image.title="Willo Local" \
    org.opencontainers.image.description="Willo Local's on-device orchestrator" \
    org.opencontainers.image.source="https://github.com/OxyHQ/willo-ha" \
    org.opencontainers.image.licenses="MIT"
