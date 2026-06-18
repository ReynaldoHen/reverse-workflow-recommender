FROM node:20-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package*.json ./
RUN npm install --omit=dev

# App source
COPY . .

EXPOSE 5005

# Production start (no nodemon)
CMD ["npm", "start"]
