FROM node:20-bookworm-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty means the browser calls the API on this same Railway host.
# .env.production must not override a value already set in the environment.
ENV REACT_APP_API_URL=
ENV CI=false
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/build /app/frontend_build

ENV FRONTEND_BUILD=/app/frontend_build
ENV DEBUG=False
ENV PORT=8080

EXPOSE 8080
CMD ["python", "App.py"]
