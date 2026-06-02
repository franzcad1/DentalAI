FROM node:20-alpine

WORKDIR /app

# Install dependencies first (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

# --host 0.0.0.0 is required to accept connections from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
