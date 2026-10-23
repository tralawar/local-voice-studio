// Formatting changes only whitespace, never speaker or emotion tags.
export function formatScript(text) {
  return text.replace(/\r\n?/g, '\n').split('\n').map(line => line.trim().replace(/[\t ]+/g, ' '))
    .join('\n').replace(/\n{3,}/g, '\n\n').trim();
}
export function wordCount(text) {
  return text.trim() ? text.trim().split(/\s+/u).length : 0;
}
export function maskSpeechTags(text) {
  // One space per UTF-16 code unit keeps suggestion offsets aligned.
  return text.replace(/<\|speaker:\d+\|>|\[[^\]\n]*\]/g, value => ' '.repeat(value.length));
}
