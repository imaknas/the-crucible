import fs from 'fs';
import path from 'path';

const newVersion = process.argv[2];

if (!newVersion) {
  console.error('Error: No version provided.');
  process.exit(1);
}

const rootDir = process.cwd();

// 1. Sync backend/pyproject.toml
const pyprojectPath = path.join(rootDir, 'backend', 'pyproject.toml');
if (fs.existsSync(pyprojectPath)) {
  let content = fs.readFileSync(pyprojectPath, 'utf8');
  content = content.replace(/^version = ".*"$/m, `version = "${newVersion}"`);
  fs.writeFileSync(pyprojectPath, content);
  console.log(`✅ Updated backend/pyproject.toml to ${newVersion}`);
}

// 2. Sync frontend/package.json
const frontendPkgPath = path.join(rootDir, 'frontend', 'package.json');
if (fs.existsSync(frontendPkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(frontendPkgPath, 'utf8'));
  pkg.version = newVersion;
  fs.writeFileSync(frontendPkgPath, JSON.stringify(pkg, null, 2) + '\n');
  console.log(`✅ Updated frontend/package.json to ${newVersion}`);
}
