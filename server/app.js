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

app.use(express.static(PUBLIC));

// Lobby management
const lobbies = new Map();

class Lobby {
  constructor(code) {
    this.code = code;
    this.players = new Map();
    this.createdAt = Date.now();
    this.timeout = setTimeout(() => this.disband(), 60 * 60 * 1000);
  }
  
  addPlayer(socket, username) {
    if (this.players.size >= 50) throw new Error('Lobby is full');
    
    const isFirstPlayer = this.players.size === 0;
    this.players.set(socket.id, {
      username,
      lastActive: Date.now(),
      timeout: setInterval(() => {
        if (Date.now() - this.players.get(socket.id).lastActive > 600000) {
          this.removePlayer(socket.id, 'inactivity');
        }
      }, 30000)
    });
    
    socket.join(this.code);
    this.updateActivity(socket.id);
    this.broadcastPlayerList();
    
    // Notify about new player (except the joining player)
    if (!isFirstPlayer) {
      socket.to(this.code).emit('player-joined', username);
    }
    
    return isFirstPlayer;
  }
  
  removePlayer(socketId, reason) {
    const player = this.players.get(socketId);
    if (!player) return;
    
    clearInterval(player.timeout);
    this.players.delete(socketId);
    io.to(this.code).emit('player-left', {
      username: player.username,
      reason
    });
    
    if (this.players.size === 0) {
      clearTimeout(this.timeout);
      lobbies.delete(this.code);
    } else {
      this.broadcastPlayerList();
    }
  }
  
  updateActivity(socketId) {
    const player = this.players.get(socketId);
    if (player) player.lastActive = Date.now();
  }
  
  broadcastPlayerList() {
    const players = Array.from(this.players.values()).map(p => p.username);
    io.to(this.code).emit('player-list', players);
  }
  
  disband() {
    io.to(this.code).emit('lobby-disbanded');
    this.players.forEach((_, socketId) => this.removePlayer(socketId));
    lobbies.delete(this.code);
  }
}

// Socket.IO handlers
io.on('connection', (socket) => {
  let currentLobby = null;
  
  socket.on('create-lobby', (username) => {
    try {
      const code = generateSlug(2, { format: 'kebab' });
      lobbies.set(code, new Lobby(code));
      currentLobby = code;
      const isHost = lobbies.get(code).addPlayer(socket, username);
      socket.emit('lobby-created', code);
    } catch (error) {
      socket.emit('error', error.message);
    }
  });
  
  socket.on('join-lobby', ({ code, username }) => {
    const lobby = lobbies.get(code.toLowerCase());
    if (!lobby) return socket.emit('error', 'Invalid lobby code');
    
    try {
      const isHost = lobby.addPlayer(socket, username);
      currentLobby = code.toLowerCase();
      socket.emit('lobby-joined', Array.from(lobby.players.values())[0].username);
    } catch (error) {
      socket.emit('error', error.message);
    }
  });
  
  socket.on('chat-message', (message) => {
    const lobby = lobbies.get(currentLobby);
    if (!lobby) return;
    
    lobby.updateActivity(socket.id);
    io.to(currentLobby).emit('chat-message', {
      username: lobby.players.get(socket.id).username,
      message
    });
  });
  
  socket.on('disconnect', () => {
    if (currentLobby) {
      const lobby = lobbies.get(currentLobby);
      if (lobby) lobby.removePlayer(socket.id, 'disconnection');
    }
  });
});

server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
