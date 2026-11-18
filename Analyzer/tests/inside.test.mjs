import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { inside } from '../lib/exports.mjs';

test('inside() accepts a root reached through a junction and still refuses escapes', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'rx-inside-'));
  try {
    const real = path.join(base, 'real');
    await fs.mkdir(real);
    await fs.writeFile(path.join(real, 'a.txt'), 'x');
    await fs.writeFile(path.join(base, 'secret.txt'), 'y');
    const link = path.join(base, 'link');
    await fs.symlink(real, link, 'junction');
    assert.equal(await inside(link, 'a.txt'), await fs.realpath(path.join(real, 'a.txt')));
    await assert.rejects(inside(link, '../secret.txt'));
  } finally {
    await fs.rm(base, { recursive: true, force: true });
  }
});
