# frontend/Dockerfile
# Stage 1: build
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
# npm ci: 按 package-lock.json 确定性安装 (npm install 会浮动解析依赖)
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: serve with nginx
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
