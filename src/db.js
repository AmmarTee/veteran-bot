import sqlite3 from 'sqlite3';
import path from 'node:path';
import fs from 'node:fs';

export function openDb(filePath) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const db = new sqlite3.Database(filePath);
  db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS config (
      guild_id TEXT PRIMARY KEY,
      coin_hub_channel_id TEXT,
      leaderboard_channel_id TEXT,
      shop_channel_id TEXT,
      admin_tx_channel_id TEXT,
      fee_rate REAL DEFAULT 0.08,
      scarcity_threshold INTEGER DEFAULT 10
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS users (
      discord_id TEXT PRIMARY KEY,
      wallet_balance INTEGER DEFAULT 0,
      escrow_balance INTEGER DEFAULT 0,
      lifetime_earned INTEGER DEFAULT 0,
      lifetime_spent INTEGER DEFAULT 0,
      streak_days INTEGER DEFAULT 0,
      last_daily_at TEXT,
      badges TEXT DEFAULT '[]',
      flags TEXT DEFAULT '[]'
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS listings (
      listing_id TEXT PRIMARY KEY,
      guild_id TEXT,
      seller_id TEXT,
      sku TEXT,
      qty INTEGER,
      unit_price INTEGER,
      fee_rate REAL,
      expires_at TEXT,
      status TEXT,
      message_channel_id TEXT,
      message_id TEXT
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS orders (
      order_id TEXT PRIMARY KEY,
      guild_id TEXT,
      buyer_id TEXT,
      total INTEGER,
      escrow INTEGER,
      fee INTEGER,
      status TEXT
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS order_lines (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id TEXT,
      listing_id TEXT,
      qty INTEGER,
      price INTEGER
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS transactions (
      tx_id TEXT PRIMARY KEY,
      guild_id TEXT,
      type TEXT,
      actor_id TEXT,
      amount INTEGER,
      reason TEXT,
      meta TEXT,
      created_at TEXT
    )`);
  });
  return db;
}

export function getUser(db, discordId) {
  return new Promise((resolve, reject) => {
    db.get('SELECT * FROM users WHERE discord_id = ?', [discordId], (err, row) => {
      if (err) return reject(err);
      if (row) return resolve(row);
      db.run('INSERT INTO users(discord_id) VALUES(?)', [discordId], (e) => {
        if (e) return reject(e);
        db.get('SELECT * FROM users WHERE discord_id = ?', [discordId], (e2, r2) => {
          if (e2) return reject(e2);
          resolve(r2);
        });
      });
    });
  });
}

export function updateBalances(db, discordId, deltaWallet, deltaEscrow) {
  return new Promise((resolve, reject) => {
    db.run(
      'UPDATE users SET wallet_balance = wallet_balance + ?, escrow_balance = escrow_balance + ? WHERE discord_id = ?',
      [deltaWallet, deltaEscrow, discordId],
      function (err) {
        if (err) return reject(err);
        resolve(this.changes);
      }
    );
  });
}

export function getConfig(db, guildId) {
  return new Promise((resolve, reject) => {
    db.get('SELECT * FROM config WHERE guild_id = ?', [guildId], (err, row) => {
      if (err) return reject(err);
      resolve(row || null);
    });
  });
}

export function setConfig(db, guildId, patch) {
  return new Promise((resolve, reject) => {
    getConfig(db, guildId).then((cur) => {
      const merged = { ...(cur || { guild_id: guildId }), ...patch };
      const cols = ['guild_id','coin_hub_channel_id','leaderboard_channel_id','shop_channel_id','admin_tx_channel_id','fee_rate','scarcity_threshold'];
      const vals = cols.map((k) => merged[k] ?? null);
      db.run(
        `INSERT INTO config(${cols.join(',')}) VALUES(${cols.map(() => '?').join(',')})
         ON CONFLICT(guild_id) DO UPDATE SET
           coin_hub_channel_id=excluded.coin_hub_channel_id,
           leaderboard_channel_id=excluded.leaderboard_channel_id,
           shop_channel_id=excluded.shop_channel_id,
           admin_tx_channel_id=excluded.admin_tx_channel_id,
           fee_rate=excluded.fee_rate,
           scarcity_threshold=excluded.scarcity_threshold`,
        vals,
        (err) => (err ? reject(err) : resolve(merged))
      );
    }, reject);
  });
}

export function createListing(db, row) {
  return new Promise((resolve, reject) => {
    db.run(
      'INSERT INTO listings(listing_id,guild_id,seller_id,sku,qty,unit_price,fee_rate,expires_at,status,message_channel_id,message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
      [row.listing_id,row.guild_id,row.seller_id,row.sku,row.qty,row.unit_price,row.fee_rate,row.expires_at,row.status,row.message_channel_id,row.message_id],
      (err) => (err ? reject(err) : resolve(row))
    );
  });
}

export function getActiveListings(db, guildId) {
  return new Promise((resolve, reject) => {
    db.all('SELECT * FROM listings WHERE guild_id = ? AND status = "active"', [guildId], (err, rows) => {
      if (err) return reject(err);
      resolve(rows || []);
    });
  });
}

export function logTx(db, tx) {
  return new Promise((resolve, reject) => {
    db.run(
      'INSERT INTO transactions(tx_id,guild_id,type,actor_id,amount,reason,meta,created_at) VALUES(?,?,?,?,?,?,?,?)',
      [tx.tx_id, tx.guild_id, tx.type, tx.actor_id, tx.amount, tx.reason, JSON.stringify(tx.meta||{}), new Date().toISOString()],
      (err) => (err ? reject(err) : resolve(tx))
    );
  });
}

