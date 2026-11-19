import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { Express } from 'express';
import { one, run, transaction, now, type DB } from './db.js';

export function installIdentity(app: Express, db: DB) {
  const secret = readFileSync('/run/secrets/warning_integration', 'utf8').trim();
  if (secret.length < 32) throw new Error('Missing warning integration secret');
  db.exec(`CREATE TABLE IF NOT EXISTS unified_users (
    account_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id)
  )`);

  app.use('/api', (req, res, next) => {
    if (req.method === 'GET' && req.path === '/health') return next();
    if (/^\/(login|logout|password|admin\/users)(\/|$)/.test(req.path))
      return res.status(404).json({ error: '请使用食品安全助手管理账号' });

    const identity = req.get('X-Warning-Identity') || '';
    const signature = req.get('X-Warning-Signature') || '';
    const parts = /^([a-f0-9-]{36}):(admin|user):(\d+)$/.exec(identity);
    if (!parts || Math.abs(Date.now() / 1000 - Number(parts[3])) > 30 || !/^[a-f0-9]{64}$/.test(signature))
      return res.status(401).json({ error: '请先登录' });
    const expected = createHmac('sha256', secret).update(identity).digest();
    if (!timingSafeEqual(expected, Buffer.from(signature, 'hex')))
      return res.status(401).json({ error: '请先登录' });

    const [, accountId, role] = parts;
    if (req.path.startsWith('/admin/') && role !== 'admin')
      return res.status(403).json({ error: '需要管理员权限' });
    const existing = one(db, 'SELECT user_id FROM unified_users WHERE account_id=?', accountId);
    const id = existing?.user_id ?? transaction(db, () => {
      const mapped = one(db, 'SELECT user_id FROM unified_users WHERE account_id=?', accountId);
      if (mapped) return mapped.user_id;
      const user = run(db, 'INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
        'unified_' + randomUUID(), '', 'user', now());
      run(db, 'INSERT INTO unified_users(account_id,user_id) VALUES(?,?)', accountId, user.lastInsertRowid);
      return Number(user.lastInsertRowid);
    });
    req.user = { id, role: role === 'admin' ? 'developer' : 'user' };
    next();
  });
}
