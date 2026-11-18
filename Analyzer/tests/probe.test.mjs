import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { gzipSync } from 'node:zlib';
import { probe } from '../scripts/probe-export-structure.mjs';

// A tiny synthetic export: two sheets with a number and a name, one custom attribute.
async function synthetic() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'rx-probe-'));
  const resource = path.join(root, 'Resource');
  const guids = ['11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222'];
  const sheets = [['A101', 'Ground floor'], ['A102', 'First floor']];
  const attrs = [null, ['name', '__name__'], ['category', '__category__'], ['ElementId', '__revit__'],
    ['Sheet Number', 'Identity Data', null, '', null, 'Sheet Number'], ['Sheet Name', 'Identity Data', null, '', null, 'Sheet Name'],
    ['Secret Custom', 'Identity Data', null, '', null, 'Secret Custom']];
  const vals = ['A101 - Ground floor', 'Revit Sheets', '1001', 'A101', 'Ground floor', 'x', 'A102 - First floor', '1002', 'A102', 'First floor'];
  const avs = [1, 0, 2, 1, 3, 2, 4, 3, 5, 4, 6, 5, 1, 6, 2, 1, 3, 7, 4, 8, 5, 9, 6, 5];
  const offs = [0, 0, 6, 12];
  const ids = ['', 'ext-1', 'ext-2'];
  await fs.mkdir(resource, { recursive: true });
  for (const [name, data] of Object.entries({ attrs, vals, avs, ids, offs })) {
    await fs.writeFile(path.join(resource, `objects_${name}.json.gz`), gzipSync(JSON.stringify(data)));
  }
  for (let index = 0; index < 2; index++) {
    const folder = path.join(resource, 'Sheets', guids[index]);
    await fs.mkdir(folder, { recursive: true });
    await fs.writeFile(path.join(folder, `${sheets[index][0]} - ${sheets[index][1]}.pdf`), 'pdf');
  }
  const manifest = { type: 'design', name: 'Model.rvt', children: [{ type: 'folder', name: 'Sheets', children:
    sheets.map(([number, name], index) => ({ type: 'geometry', viewableID: guids[index], name: `${number} - ${name}`, role: '2d' })) }] };
  await fs.writeFile(path.join(root, 'bubble.json'), JSON.stringify(manifest));
  return root;
}

test('the probe ties files to sheets and prints no names by default', async () => {
  const root = await synthetic();
  try {
    const before = await fs.readdir(root);
    const report = await probe(root);
    assert.equal(report.mapping.sheetElements, 2);
    assert.equal(report.mapping.pdfFiles, 2);
    assert.equal(report.mapping.pdfStemEqualsViewableName, 2);
    assert.equal(report.mapping.pdfStemEqualsNumberDashName, 2);
    assert.equal(report.mapping.viewableHasGuid, 2);
    assert.equal(report.properties.sheetsAndViews.builtIn['Sheet Number'].nonEmpty, 2);
    assert.equal(report.properties.sheetsAndViews.otherAttributeNames, 1, 'counted, not named');
    const text = JSON.stringify(report);
    for (const secret of ['Secret Custom', 'Ground floor', 'A101', 'Model.rvt', root]) assert.ok(!text.includes(secret), secret);
    const named = await probe(root, { showNames: true });
    assert.ok('Secret Custom' in named.properties.sheetsAndViews.otherAttributeNames.shown);
    assert.deepEqual(await fs.readdir(root), before, 'nothing is written');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
