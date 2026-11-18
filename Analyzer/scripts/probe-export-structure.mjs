// Read-only probe of one export: what is in it, and can a file be tied back to its sheet or view?
// Prints structure and counts only: no model, sheet, view or file name, no path, no value.
// Attribute names are printed only when they are on the built-in list below; others are counted.
// Pass --show-names to also print the names of the other attributes (they can be project specific).
//
//   node scripts/probe-export-structure.mjs <export output folder> [--show-names]
//
// Nothing is written. The property database is opened read-only through the Analyzer's own reader.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PropertyStore } from '../lib/properties.mjs';

const BUILT_IN = new Set(['Sheet Number', 'Sheet Name', 'Name', 'View Name', 'Title on Sheet', 'Current Revision',
  'Current Revision Date', 'Current Revision Description', 'Current Revision Issued', 'Current Revision Issued By',
  'Current Revision Issued To', 'Sheet Issue Date', 'Appears In Sheet List', 'Approved By', 'Designed By', 'Checked By',
  'Drawn By', 'Scale', 'View Scale', 'Detail Level', 'Discipline', 'Phase', 'Phase Filter', 'View Template',
  'Sheet Width', 'Sheet Height', 'Width', 'Height', 'Scale Value    1:', 'Dependency', 'View Type', 'ElementId', 'Category']);

async function walk(root, prefix = '') {
  const files = [];
  for (const item of await fs.readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${item.name}` : item.name;
    if (item.isSymbolicLink()) continue;
    if (item.isDirectory()) files.push(...await walk(root, relative));
    else if (item.isFile()) files.push(relative);
  }
  return files;
}

function nodes(node, found = []) {
  found.push(node);
  for (const child of node.children || []) nodes(child, found);
  return found;
}

export async function probe(outputFolder, { showNames = false } = {}) {
  const root = path.resolve(outputFolder);
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'bubble.json'), 'utf8'));
  const files = await walk(root);
  const report = { schema: 'rx-export-probe', version: 1 };

  // 1. Files by folder depth-2 prefix and extension: counts only.
  const byKind = {};
  for (const file of files) {
    const parts = file.split('/');
    const kind = `${parts[0]}/${parts.length > 2 ? '*' : ''}${path.extname(file).toLowerCase() || '(none)'}`;
    byKind[kind] = (byKind[kind] || 0) + 1;
  }
  report.files = { total: files.length, byKind };

  // 2. The manifest: node types, the keys each type carries (never values).
  const all = nodes(manifest);
  const keysByType = {};
  const countByType = {};
  for (const node of all) {
    const type = node.type || '(no type)';
    countByType[type] = (countByType[type] || 0) + 1;
    keysByType[type] = [...new Set([...(keysByType[type] || []), ...Object.keys(node)])].sort();
  }
  report.manifest = { topKeys: Object.keys(manifest).sort(), countByType, keysByType };

  // 3. The property database: categories (Revit's own names) and the attributes of sheets and views.
  const resource = path.join(root, 'Resource');
  const hasProperties = files.includes('Resource/objects_attrs.json.gz');
  report.properties = { present: hasProperties };
  let sheets = [];
  let externalIds = new Set();
  let viewNames = new Set();
  if (hasProperties) {
    const store = new PropertyStore(resource);
    report.properties.elements = store.rows.length;
    externalIds = new Set(store.rows.map(row => row.externalId));
    viewNames = new Set(store.rows.filter(row => /^Views?$/i.test(row.category)).map(row => row.name));
    report.properties.categories = store.categories.slice(0, 40);
    const wanted = row => /^Sheets?$/i.test(row.category) || /^Views?$/i.test(row.category);
    const attributeCounts = new Map();
    let rowsWithElementId = 0;
    for (const row of store.rows.filter(wanted)) {
      if (row.elementId !== null) rowsWithElementId++;
      store.each(row.dbId, (attr, value) => {
        if (String(attr[1]).startsWith('__')) return;   // the database's own bookkeeping
        const name = String(attr[5] || attr[0]);
        const entry = attributeCounts.get(name) || { elements: 0, nonEmpty: 0 };
        entry.elements++;
        if (value !== '' && value !== null && value !== undefined) entry.nonEmpty++;
        attributeCounts.set(name, entry);
      });
    }
    const builtIn = {};
    const other = { names: 0, shown: {} };
    for (const [name, entry] of attributeCounts) {
      if (BUILT_IN.has(name)) builtIn[name] = entry;
      else { other.names++; if (showNames) other.shown[name] = entry; }
    }
    report.properties.sheetsAndViews = {
      elements: store.rows.filter(wanted).length, withElementId: rowsWithElementId, builtIn,
      otherAttributeNames: showNames ? other : other.names,
    };
    sheets = store.rows.filter(row => /^Sheets?$/i.test(row.category)).map(row => {
      const values = {};
      store.each(row.dbId, (attr, value) => { values[String(attr[5] || attr[0])] = String(value ?? ''); });
      return { row, values };
    });
  }

  // 4. Can a file be tied back? Booleans and counts only.
  const pdfStems = files.filter(file => /\.pdf$/i.test(file)).map(file => path.basename(file, path.extname(file)));
  const viewables = all.filter(node => node.type === 'geometry');
  const names = new Set(viewables.map(node => String(node.name ?? '')));
  const check = {
    viewables: viewables.length, pdfFiles: pdfStems.length,
    viewableHasGuid: viewables.filter(node => node.viewableID || node.guid).length,
    pdfStemEqualsViewableName: pdfStems.filter(stem => names.has(stem)).length,
    sheetElements: sheets.length,
    sheetNameEqualsViewableName: sheets.filter(({ row }) => names.has(row.name)).length,
    pdfStemEqualsNumberDashName: sheets.filter(({ values }) => pdfStems.includes(`${values['Sheet Number']} - ${values['Sheet Name']}`)).length,
    viewableIdEqualsExternalId: viewables.filter(node => externalIds.has(String(node.viewableID || node.guid || ''))).length,
    viewableIdLooksLikeAnElementUniqueId: viewables.filter(node => /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}-[0-9a-f]{8}$/i.test(String(node.viewableID || node.guid || ''))).length,
    viewNameEqualsViewableName: [...viewNames].filter(name => names.has(name)).length,
    nodeKeysThatLookLikeAnElementId: [...new Set(viewables.flatMap(node => Object.keys(node)).filter(key => /element.?id|revit.?id|uniqueid|external/i.test(key)))],
  };
  report.mapping = check;

  // 5. Where the deliverables sit: counts of files and of folders (the 3D views are folders).
  const guidFolder = file => file.split('/').slice(0, -1).find(part => /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(part));
  const ext = pattern => files.filter(file => pattern.test(file));
  const viewFiles = ext(/\.(svf|f2d)$/i);
  const folders = new Map();
  for (const file of viewFiles) { const key = guidFolder(file) ?? file.split('/').slice(0, -1).join('/'); folders.set(key, (folders.get(key) || 0) + 1); }
  report.deliverables = {
    pdf: ext(/\.pdf$/i).length, dwg: ext(/\.dwg$/i).length, ifc: ext(/\.ifc$/i).length, f2d: ext(/\.f2d$/i).length, svf: ext(/\.svf$/i).length,
    pdfInGuidFolder: ext(/\.pdf$/i).filter(file => guidFolder(file)).length,
    dwgInGuidFolder: ext(/\.dwg$/i).filter(file => guidFolder(file)).length,
    viewFolders: folders.size, viewFoldersWithOneViewFile: [...folders.values()].filter(count => count === 1).length,
    dwgStemEqualsViewableName: ext(/\.dwg$/i).filter(file => names.has(path.basename(file, path.extname(file)))).length,
  };
  return report;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const folder = process.argv[2];
  if (!folder || folder.startsWith('--')) {
    console.error('Usage: node scripts/probe-export-structure.mjs <export output folder> [--show-names]');
    process.exit(2);
  }
  try {
    console.log(JSON.stringify(await probe(folder, { showNames: process.argv.includes('--show-names') }), null, 2));
  } catch (error) {
    console.error(`Probe failed: ${error.code || error.name}`);
    process.exit(1);
  }
}
