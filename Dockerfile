FROM python:3-alpine

LABEL maintainer="Almost Perfect Software OÜ"

RUN apk add --update --no-cache helm git  && adduser -D ked

USER ked

WORKDIR /home/ked

COPY --chown=ked:ked --chmod=755 . .

RUN helm plugin install https://github.com/hypnoglow/helm-s3.git && pip install --upgrade --no-cache-dir \
  -r requirements.txt

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD [ -f /tmp/healthz ] || exit 1

ENTRYPOINT ["python3", "./ked.py"]
