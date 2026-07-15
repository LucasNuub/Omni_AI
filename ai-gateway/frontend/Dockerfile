# Build Stage
FROM node:24-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve Stage
FROM node:24-alpine
WORKDIR /app
RUN npm install -g sirv-cli
COPY --from=builder /app/build ./build
EXPOSE 3000
CMD ["sirv", "build", "--host", "0.0.0.0", "--port", "3000", "--single"]
