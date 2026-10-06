FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/app.conf /etc/nginx/snippets/mymenu-app.conf
# Mounted from secrets/tls by docker-compose when LAN HTTPS is set up; empty otherwise.
RUN mkdir -p /etc/nginx/tls
COPY --from=build /app/dist /usr/share/nginx/html
