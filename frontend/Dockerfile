# ==========================================
# AutoTrade Frontend Dockerfile
# ==========================================
# Multi-stage build: Node → Nginx

# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files first for caching
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build for production
RUN npm run build


# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port 80
COPY .htpasswd /etc/nginx/conf.d/.htpasswd
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
COPY .htpasswd /etc/nginx/conf.d/.htpasswd
COPY .htpasswd /etc/nginx/conf.d/.htpasswd
