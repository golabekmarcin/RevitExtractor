import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { PropertyStore } from './properties.mjs';

export const slash = value => value.split(path.sep).join('/');
export const fileUrl = (id, relative) => `/files/${id}/${slash(relative).split('/').map(encodeURIComponent).join('/')}`;

export async function inside(root, relative) {
  // Resolve both sides: a root reached through a junction or symlink must still match its targets.
  const realRoot = await fs.realpath(root);
  const target = await fs.realpath(path.resolve(realRoot, relative));
  const rel = path.relative(realRoot, target);
  if (rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) throw new Error('Ścieżka poza wybranym folderem.');
  return target;
}

export async function walk(root, prefix = '') {
  const files = [];
  for (const item of await fs.readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = path.join(prefix, item.name);
    // Never follow junctions or symlinks outside the selected export.
    if (item.isSymbolicLink()) continue;
    if (item.isDirectory()) files.push(...await walk(root, relative));
    else if (item.isFile()) files.push(slash(relative));
  }
  return files;
}

export async function resolveOutput(input) {
  const candidate = path.resolve(input.trim().replace(/^"|"$/g, ''));
  for (const root of [candidate, path.join(candidate, 'output'), path.dirname(candidate)]) {
    try {
      const real = await fs.realpath(root);
      const bubble = await inside(real, 'bubble.json');
      const manifest = JSON.parse(await fs.readFile(bubble, 'utf8'));
      await inside(real, 'Resource');
      if (manifest.type === 'design') return { root: real, manifest };
    } catch { /* Try output or the parent of Resource. */ }
  }
  throw new Error('Nie znaleziono eksportu. Wybierz folder output zawierający bubble.json i Resource.');
}

export class ExportRegistry {
  constructor() { this.items = new Map(); this.stores = new Map(); }

  async register(input) {
    const { root, manifest } = await resolveOutput(input);
    const id = createHash('sha256').update(root).digest('hex').slice(0, 16);
    const files = await walk(root);
    const views = [];
    const viewNodes = new Map();
    const visit = (node, group = '') => {
      if (node.type === 'geometry') viewNodes.set(node.viewableID || node.guid, { ...node, group });
      for (const child of node.children || []) visit(child, node.type === 'folder' ? node.name : group);
    };
    visit(manifest);
    for (const relative of files.filter(file => /\.(svf|pdf)$/i.test(file))) {
      const parts = relative.split('/');
      const guid = parts.find(part => /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(part));
      const meta = viewNodes.get(guid) || {};
      const extension = path.extname(relative);
      const base = relative.slice(0, -extension.length);
      const thumbnail = [`${base}4.png`, `${base}2.png`, `${base}1.png`].find(x => files.includes(x));
      views.push({ id: guid || relative, role: extension.toLowerCase() === '.svf' ? '3d' : '2d', name: meta.name || path.basename(base), group: parts[1] || meta.group || 'Widoki', path: relative, url: fileUrl(id, relative), thumbnail: thumbnail ? fileUrl(id, thumbnail) : null });
    }
    views.sort((a, b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name, 'pl', { numeric: true }));
    const stat = await fs.stat(path.join(root, 'bubble.json'));
    const info = {
      id, root, name: manifest.name || path.basename(root), modified: stat.mtime.toISOString(),
      properties: manifest.properties?.['Document Information'] || {}, views,
      fileCount: files.length, pdfCount: views.filter(x => x.role === '2d').length,
      modelCount: views.filter(x => x.role === '3d').length,
      preview: files.includes('preview.png') ? fileUrl(id, 'preview.png') : null,
      hasProperties: ['attrs', 'vals', 'avs', 'ids', 'offs'].every(x => files.includes(`Resource/objects_${x}.json.gz`)),
      hasSqlite: files.includes('Resource/model.sdb'),
      propertyUrl: fileUrl(id, 'Resource/')
    };
    this.items.set(id, info);
    this.stores.delete(id);
    return info;
  }

  get(id) {
    const item = this.items.get(id);
    if (!item) throw new Error('Eksport nie jest otwarty.');
    return item;
  }

  store(id) {
    const item = this.get(id);
    if (!item.hasProperties) throw new Error('Brak kompletu plików objects_*.json.gz.');
    if (!this.stores.has(id)) {
      // Keep one large property database in memory at a time.
      this.stores.clear();
      this.stores.set(id, new PropertyStore(path.join(item.root, 'Resource')));
    }
    return this.stores.get(id);
  }

  async discover(parent) {
    const candidates = [];
    for (const entry of await fs.readdir(parent, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || entry.name === 'Analyzer') continue;
      const root = path.join(parent, entry.name, 'output');
      try {
        const stat = await fs.stat(path.join(root, 'bubble.json'));
        candidates.push({ root, time: stat.mtimeMs });
      } catch { /* Not an export. */ }
    }
    candidates.sort((a, b) => b.time - a.time);
    for (const candidate of candidates) {
      try { await this.register(candidate.root); }
      catch (error) { console.warn(`Pomijam niepełny eksport: ${error.message}`); }
    }
  }
}
