# Imagen de la interfaz web (Django) del prototipo.
# Contexto de build = raíz del repositorio, porque la app lee config/domains/.
#
# Etapa 1: compila el CSS/JS con Vite (el dist/ no está versionado).
FROM node:24-slim AS assets
WORKDIR /build
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/vite.config.js ./
COPY webapp/assets ./assets
COPY webapp/recommender/templates ./recommender/templates
RUN npm run build

# Etapa 2: imagen final con Python y gunicorn.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

COPY webapp/requirements.txt ./webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

# La webapp reutiliza los pasos 08/10 de src/ y las preferencias congeladas.
COPY config ./config
COPY src ./src
COPY artifacts_por_dominio ./artifacts_por_dominio
COPY webapp ./webapp
COPY --from=assets /build/recommender/static/dist ./webapp/recommender/static/dist

WORKDIR /app/webapp
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=0 python manage.py collectstatic --noinput

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
