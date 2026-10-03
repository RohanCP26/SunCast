FROM node:20-bookworm-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
# Empty means the browser calls the API on this same Railway host.
# .env.production must not override a value already set in the environment.
ENV REACT_APP_API_URL=
ENV CI=false
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
# Railway kills the build with exit 137 when pip unpacks numpy, scipy,
# pandas, and scikit-learn in one process. Install the large wheels one at a time.
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2
COPY backend/requirements.txt .
RUN pip install --only-binary=:all: "numpy==1.24.0" \
 && pip install --only-binary=:all: "scipy==1.11.0" \
 && pip install --only-binary=:all: "pandas==2.0.0" \
 && pip install --only-binary=:all: "scikit-learn==1.3.0" "joblib==1.3.0" \
 && pip install --only-binary=:all: -r requirements.txt
COPY backend/ ./
COPY --from=web /web/build /app/frontend_build

ENV FRONTEND_BUILD=/app/frontend_build
ENV DEBUG=False
ENV PORT=8080

EXPOSE 8080
CMD ["python", "App.py"]
