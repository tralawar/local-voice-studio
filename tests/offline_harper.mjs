import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LocalLinter } from 'harper.js';
import { binaryInlined as binary } from 'harper.js/binaryInlined';
test('Harper loads local WASM and checks spelling/grammar with fetch denied', async () => {
  const localFetch = globalThis.fetch;
  globalThis.fetch = (url, ...args) => {
    if (String(url).startsWith('data:application/wasm')) return localFetch(url, ...args);
    throw new Error('Network disabled by offline test');
  };
  const linter = new LocalLinter({ binary });
  const results = await linter.lint('The the observatory opens. We has a misspelld word.', { language: 'plaintext' });
  assert.ok(results.length >= 3);
  await linter.dispose();
});
