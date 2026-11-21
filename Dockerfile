FROM python:3.12-alpine
LABEL org.opencontainers.image.source="https://github.com/theashutoshn/Folbum" \
      org.opencontainers.image.documentation="https://github.com/theashutoshn/Folbum#readme"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY LICENSE ./LICENSE
COPY app ./app
COPY static ./static
RUN apk add --no-cache tzdata && mkdir -p /app/data && addgroup -S zima && adduser -S zima -G zima && chown -R zima:zima /app/data
USER zima
EXPOSE 8765
CMD ["python", "-m", "app.server"]
