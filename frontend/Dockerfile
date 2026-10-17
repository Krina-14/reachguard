# Multi-stage Dockerfile for ReachGuard Frontend
# Stage 1: Build the production static bundle using Node.js
FROM node:20-alpine AS builder

WORKDIR /app

# Cache dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy application source and compile
COPY . .
RUN npm run build

# Stage 2: Serve static bundle via Nginx
FROM nginx:alpine

# Remove default static pages
RUN rm -rf /usr/share/nginx/html/*

# Copy custom Nginx configuration (reverse proxy, SPA fallback, gzip, security headers)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled SPA bundle from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
