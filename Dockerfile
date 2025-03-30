FROM node:18-alpine
WORKDIR /app
COPY server/package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["node", "server/app.js"]