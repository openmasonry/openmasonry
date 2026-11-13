# The pinned core, and nothing else of the source: exactly the files the manifest lists
# (src/openmasonry/protocol.manifest), copied one by one. A listed file that is missing stops the build.
FROM python:3.12-slim AS core
COPY . /repo
RUN set -eu; mkdir /core; cd /repo; \
    while IFS= read -r f; do \
      mkdir -p "/core/$(dirname "$f")"; cp "$f" "/core/$f"; \
    done < src/openmasonry/protocol.manifest

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl gnupg \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/gh.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/gh.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/gh.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && pip install --no-cache-dir opentimestamps-client==0.7.2 \
 && apt-get purge -y gnupg && rm -rf /var/lib/apt/lists/*
ENV GIT_CONFIG_GLOBAL=/home/tyler/.config/gitconfig
RUN useradd -m -u 1000 tyler
USER tyler
WORKDIR /home/tyler
# The verifier is baked into the image at build time: code merged later into the repository
# never runs with the witness key until an operator rebuilds (after the amendment ratifying it).
# The witness signs only while the digest of this copy equals the ledger's @protocol pin, so the image
# holds every file of the pinned core, the manifest and the workflows included, and no other code of
# the package: the witness imports only pinned modules.
COPY --from=core --chown=tyler:tyler /core /home/tyler/verifier
COPY --chown=tyler:tyler canon /home/tyler/verifier/canon
COPY --chown=tyler:tyler node/witness.py /home/tyler/witness.py
COPY --chown=tyler:tyler node/entrypoint.sh /home/tyler/entrypoint.sh
ENV OM_WITNESS_VERIFIER=/home/tyler/verifier/src
ENV OM_NO_CACHE=1
ENTRYPOINT ["/bin/sh", "/home/tyler/entrypoint.sh"]
