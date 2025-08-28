const express = require('express');
const path = require('path');
const { Server } = require('socket.io');
const http = require('http');
const https = require('https');
const { generateSlug } = require('random-word-slugs');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

const PORT = 3000;
const PUBLIC = path.join(__dirname, '../public');
const COLOR_PALETTE = [
  '#ECB287', '#5D8B5F', '#F9CDC3', '#F1D074', 
  '#FC7E04', '#61216A', '#BDCC30', '#F9E9E5', 
  '#F33F71', '#2FA8B5', '#FCEFDB', '#F6E1E4',
  '#DFB1D5', '#F1D3C4', '#AFC2DA', '#F4D0B4',
  '#242329', '#37707D', '#EBDBD7', '#CB82B2',
  '#B8D097', '#DFE4C0', '#E6E5EB'
];

const GA_MEASUREMENT_ID = 'G-4K7ZSG6XT3';
const GA_API_SECRET = 'fNkFBH2HTA2WQ5qvTBU8UA';

function sendGAEvent(clientIP) {
  const postData = JSON.stringify({
    client_id: clientIP || '555.abc.123',
    events: [
      {
        name: 'cv_download',
        params: {
          event_category: 'PDF',
          event_label: 'CV Download',
          value: 1
        }
      }
    ]
  });

  const options = {
    hostname: 'www.google-analytics.com',
    path: `/mp/collect?measurement_id=${GA_MEASUREMENT_ID}&api_secret=${GA_API_SECRET}`,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(postData)
    }
  };

  const req = https.request(options, res => {
    res.on('data', () => {});
  });

  req.on('error', err => {
    console.error('GA4 event failed:', err.message);
  });

  req.write(postData);
  req.end();
}

app.use(express.static(PUBLIC));

app.get('/cv', (req, res) => {
  sendGAEvent(req.ip);
  res.sendFile(path.join(PUBLIC, 'cv.pdf'));
});

app.get('/bollyvault', (req, res) => {
  res.sendFile(path.join(PUBLIC, 'bollyvault.html'));
});

app.get('/vna', (req, res) => {
  const version = req.query.version;
  let filename = 'vna.html';
  if(version) {
    filename = 'vna' + version + '.html';
  }
  res.sendFile(path.join(PUBLIC, filename));
});

app.get('/flashchat', (req, res) => {
  res.sendFile(path.join(PUBLIC, 'flashchat.html'));
});

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
    const entries = Array.from(this.players.entries());
    const hostId = entries[0]?.[0]; // First entry's key is host
    return entries.map(([socketId, player]) => ({
      username: player.username,
      color: player.color,
      isHost: socketId === hostId
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
  
   canReconnect(socketId) {
      const player = this.players.get(socketId);
      if (!player) return false;
      
      // Check if player was disconnected but lobby still exists
      const isWithinTimeWindow = Date.now() - player.lastActive < 600000; // 10 minutes
      const isLobbyValid = Date.now() - this.createdAt < 60 * 60 * 1000; // 1 hour
      
      return isWithinTimeWindow && isLobbyValid;
    }
    
    reconnectPlayer(socket, socketId) {
      const player = this.players.get(socketId);
      if (!player) return false;
      
      // Update the player's socket reference
      this.players.delete(socketId);
      player.socketId = socket.id;
      player.lastActive = Date.now();
      this.players.set(socket.id, player);
      
      // Clear old interval and set new one
      clearInterval(player.timeout);
      player.timeout = setInterval(() => {
        if (Date.now() - player.lastActive > 600000) {
          this.removePlayer(socket.id, 'inactivity');
        }
      }, 30000);
      
      socket.join(this.code);
      this.addSystemMessage(`${player.username} reconnected`, 'reconnect');
      this.broadcastPlayerList();
      
      return true;
    }
}

const lobbies = new Map();

io.on('connection', (socket) => {
  let currentLobby = null;
  
   socket.on('reconnect-attempt', ({ previousSocketId, code, username }) => {
      const lobby = lobbies.get(code.toLowerCase());
      if (!lobby) {
        socket.emit('error', 'Lobby no longer exists');
        return;
      }
      
      if (previousSocketId && lobby.canReconnect(previousSocketId)) {
        if (lobby.reconnectPlayer(socket, previousSocketId)) {
          currentLobby = code.toLowerCase();
          socket.emit('reconnect-success', {
            code: lobby.code,
            createdAt: lobby.createdAt,
            color: lobby.players.get(socket.id).color,
            players: lobby.getPlayerList(),
            messages: lobby.messages
          });
          return;
        }
      }
      
      // Fall back to normal join if reconnect not possible
      try {
        lobby.addPlayer(socket, username);
        socket.emit('lobby-info', {
          code: lobby.code,
          createdAt: lobby.createdAt,
          color: lobby.players.get(socket.id).color,
          players: lobby.getPlayerList(),
          messages: lobby.messages
        });
      } catch (error) {
        socket.emit('error', error.message);
      }
    });
   
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
    console.log(`[CHAT-MSG] From ${socket.id} in ${currentLobby}: ${message}`);
    const lobby = lobbies.get(currentLobby);
    if (!lobby) {
      console.log(`[ERROR] Lobby ${currentLobby} not found for ${socket.id}`);
      return;
    }
    
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
