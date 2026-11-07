import {i18n, t} from './i18n';
import wireMessages from '../locales/backend-messages.json';

const patterns = wireMessages.patterns.map(({pattern, ...entry}) => ({...entry, expression: new RegExp(pattern)}));

function translateKnown(value) {
  if (Object.hasOwn(wireMessages.exact, value)) return t(wireMessages.exact[value]);
  if (value.startsWith('system:') && i18n.exists(value)) return t(value);
  for (const {expression, key, params} of patterns) {
    const match = expression.exec(value);
    if (match) return t(key, Object.fromEntries(params.map((name, index) => [name, match[index + 1]])));
  }
  return value;
}

export function systemMessage(value) {
  if (typeof value !== 'string') return value;
  const exact = translateKnown(value);
  if (exact !== value) return exact;
  // Translate only recognized application errors; preserve external diagnostics and model IDs.
  return value.split('; ').map(part => {
    const match = /^([a-z0-9][a-z0-9._-]*): ([^\r\n]+)$/.exec(part);
    if (!match) return part;
    const translated = translateKnown(match[2]);
    return translated === match[2] ? part : `${match[1]}: ${translated}`;
  }).join('; ');
}
