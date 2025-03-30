FROM node:18-alpine
WORKDIR /app
COPY server/package*.json ./server/
RUN cd server && npm install --production
COPY . .
EXPOSE 3000
CMD ["node", "server/app.js"]