FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8765 DATA_DIR=/app/data
WORKDIR /app
COPY app ./app
COPY static ./static
RUN mkdir -p /app/data && addgroup -S zima && adduser -S zima -G zima && chown -R zima:zima /app/data
USER zima
EXPOSE 8765
CMD ["python", "-m", "app.server"]
