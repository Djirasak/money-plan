#!/usr/bin/env node
/**
 * Copy the lucide icons we use from node_modules into money_plan/templates/icons/
 * (committed, so Django needs no node at runtime). Add a name to ICONS and run
 * `pnpm run icons`. Used in templates with {% icon "name" "size-5" %}.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const ICONS = [
  'plus', 'save', 'trash-2', 'log-out', 'chevron-left', 'chevron-right',
  'layout-dashboard', 'square-pen', 'settings', 'search', 'lock', 'timer',
  'wrench', 'coins', 'piggy-bank', 'wallet', 'arrow-left', 'arrow-right',
  'sun', 'moon', 'languages', 'circle-check', 'circle-alert', 'info', 'x', 'grip-vertical', 'palette', 'chevron-down', 'arrow-up-right', 'arrow-down-left', 'arrow-left-right', 'user', 'mail', 'shield-check', 'camera', 'check',
];
const src = 'node_modules/lucide-static/icons';
const out = 'money_plan/templates/icons';
mkdirSync(out, { recursive: true });
for (const name of ICONS) {
  const svg = readFileSync(`${src}/${name}.svg`, 'utf8')
    .replace(/<!--[\s\S]*?-->\s*/, '')
    .replace(/\s+class="[^"]*"/, '')
    .replace(/\s+width="24"/, '')
    .replace(/\s+height="24"/, '')
    .replace(/\s+/g, ' ')
    .replace(/> </g, '><')
    .trim();
  writeFileSync(`${out}/${name}.svg`, `${svg}\n`);
}
console.log(`synced ${ICONS.length} icons`);
