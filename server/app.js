const express = require('express');
const path = require('path');
const app = express();

const PORT = 3000;
const PUBLIC = path.join(__dirname, '../public');

app.use(express.static(PUBLIC));

// Game endpoint
app.get('/game', (req, res) => {
  res.sendFile(path.join(PUBLIC, 'game.html'));
});

// Start server
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
