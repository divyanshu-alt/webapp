FROM node:22-alpine
WORKDIR /app
COPY server/package*.json ./server/
RUN cd server && npm install
COPY . .
EXPOSE 3000
CMD ["node", "server/app.js"]