import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { resolve, relative, join } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const inputs = ['package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts'];
function walk(directory, result) {
  for (const name of readdirSync(directory).sort()) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) walk(path, result);
    else result.push(relative(root, path).replaceAll('\\', '/'));
  }
}
for (const directory of ['src', 'scripts', 'tests']) walk(join(root, directory), inputs);
const source = createHash('sha256');
for (const name of inputs.sort()) source.update(name + '\0').update(readFileSync(join(root, name)));
const files = [];
walk(join(root, 'dist'), files);
const assets = {};
for (const name of files.sort()) {
  if (name === 'dist/build.json') continue;
  assets[name.slice(5)] = createHash('sha256').update(readFileSync(join(root, name))).digest('hex');
}
writeFileSync(join(root, 'dist/build.json'), JSON.stringify({ format: 1, input_sha256: source.digest('hex'), files: assets }, null, 2) + '\n');
console.log('Recorded source fingerprint and ' + Object.keys(assets).length + ' production asset hashes');
