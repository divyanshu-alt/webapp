const express = require('express');
const path = require('path');
const { Server } = require('socket.io');
const http = require('http');
const { generateSlug } = require('random-word-slugs');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

const PORT = 3000;
const PUBLIC = path.join(__dirname, '../public');
const COLOR_PALETTE = [
  '#6c5ce7', '#00b894', '#fd79a8', '#fdcb6e', '#74b9ff',
  '#55efc4', '#ff7675', '#a29bfe', '#ffeaa7', '#81ecec'
];

app.use(express.static(PUBLIC));

class Lobby {
  constructor(code) {
    this.code = code;
    this.players = new Map();
    this.messages = [];
    this.createdAt = Date.now();
    this.timeout = setTimeout(() => {
      console.log(`[LOBBY EXPIRED] ${code}`);
      this.disband();
    }, 60 * 60 * 1000);
    console.log(`[LOBBY CREATED] ${code}`);
  }
  
  addPlayer(socket, username) {
    if (this.players.size >= 50) throw new Error('Lobby is full');
    
    const color = COLOR_PALETTE[this.players.size % COLOR_PALETTE.length];
    const playerData = {
      username,
      color,
      lastActive: Date.now(),
      timeout: setInterval(() => {
        if (Date.now() - this.players.get(socket.id).lastActive > 600000) {
          console.log(`[INACTIVITY] Kicked ${username} from ${this.code}`);
          this.removePlayer(socket.id, 'inactivity');
        }
      }, 30000)
    };
    
    this.players.set(socket.id, playerData);
    socket.join(this.code);
    
    // Send lobby info and history to new player
    socket.emit('lobby-info', {
      code: this.code,
      createdAt: this.createdAt,
      color: playerData.color,
      players: this.getPlayerList(),
      messages: this.messages
    });
    
    // Notify others
    this.broadcastPlayerList();
    this.addSystemMessage(`${username} joined`, 'join');
    
    console.log(`[PLAYER JOINED] ${username} in ${this.code}`);
    return playerData;
  }
  
  removePlayer(socketId, reason) {
    const player = this.players.get(socketId);
    if (!player) return;
    
    clearInterval(player.timeout);
    this.players.delete(socketId);
    this.addSystemMessage(`${player.username} left (${reason})`, 'leave');
    
    if (this.players.size === 0) {
      clearTimeout(this.timeout);
      lobbies.delete(this.code);
    } else {
      this.broadcastPlayerList();
    }
    console.log(`[PLAYER LEFT] ${player.username} from ${this.code} (Reason: ${reason})`);
  }
  
  addSystemMessage(text, type) {
    const message = {
      type,
      text,
      timestamp: Date.now(),
      system: true
    };
    this.messages.push(message);
    io.to(this.code).emit('chat-message', message);
  }
  
  addChatMessage(socket, message) {
    const player = this.players.get(socket.id);
    if (!player) return;
    
    const chatMessage = {
      username: player.username,
      color: player.color,
      text: message,
      timestamp: Date.now()
    };
    
    this.messages.push(chatMessage);
    io.to(this.code).emit('chat-message', chatMessage);
  }
  
  getPlayerList() {
    return Array.from(this.players.values()).map(player => ({
      username: player.username,
      color: player.color,
      isHost: this.players.keys().next().value === player.socketId
    }));
  }
  
  broadcastPlayerList() {
    io.to(this.code).emit('player-list', this.getPlayerList());
  }
  
  disband() {
    io.to(this.code).emit('lobby-disbanded');
    this.players.forEach((_, socketId) => this.removePlayer(socketId));
    lobbies.delete(this.code);
  }
}

const lobbies = new Map();

io.on('connection', (socket) => {
  let currentLobby = null;
  
  socket.on('create-lobby', (username) => {
    try {
      const code = generateSlug(2, { format: 'kebab' });
      const lobby = new Lobby(code);
      lobbies.set(code, lobby);
      currentLobby = code;
      lobby.addPlayer(socket, username);
    } catch (error) {
      console.error(`[LOBBY ERROR] ${error.message}`);
      socket.emit('error', error.message);
    }
  });
  
  socket.on('join-lobby', ({ code, username }) => {
    const lobby = lobbies.get(code.toLowerCase());
    if (!lobby) {
      console.log(`[INVALID LOBBY] Attempt to join ${code}`);
      return socket.emit('error', 'Invalid lobby code');
    }
    
    try {
      currentLobby = code.toLowerCase();
      lobby.addPlayer(socket, username);
    } catch (error) {
      console.error(`[JOIN ERROR] ${error.message}`);
      socket.emit('error', error.message);
    }
  });
  
  socket.on('chat-message', (message) => {
    const lobby = lobbies.get(currentLobby);
    if (!lobby) return;
    
    lobby.addChatMessage(socket, message);
  });
  
  socket.on('disconnect', () => {
    const lobby = lobbies.get(currentLobby);
    if (lobby) {
      console.log(`[DISCONNECT] Player from ${currentLobby}`);
      lobby.removePlayer(socket.id, 'disconnected');
    }
  });
});

server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
