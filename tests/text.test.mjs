import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatScript, maskSpeechTags, wordCount } from '../src/text.js';
test('formatter preserves speech tags and Unicode while normalizing whitespace', () => {
  assert.equal(formatScript('  <|speaker:0|>  [laughs] Héllo.  \r\n\r\n\r\n 👋  Hi.  '), '<|speaker:0|> [laughs] Héllo.\n\n👋 Hi.');
  assert.equal(wordCount(' \n '), 0);
  assert.equal(wordCount('Hello there.'), 2);
});
test('masking retains original offsets and does not consume dialogue', () => {
  const text = '👋 <|speaker:0|> [laughs] This are a test.';
  const masked = maskSpeechTags(text);
  assert.equal(masked.length, text.length);
  assert.equal(masked.indexOf('This'), text.indexOf('This'));
});
