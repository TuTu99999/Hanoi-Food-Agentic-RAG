import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isExternalMarkdownLink,
  sanitizeMarkdownImage,
  sanitizeMarkdownLink,
} from '../src/lib/markdown.js';


test('markdown links allow safe URLs', () => {
  assert.equal(sanitizeMarkdownLink('/history/1'), '/history/1');
  assert.equal(sanitizeMarkdownLink('#details'), '#details');
  assert.equal(sanitizeMarkdownLink('https://example.com'), 'https://example.com');
  assert.equal(sanitizeMarkdownLink('mailto:hello@example.com'), 'mailto:hello@example.com');
});


test('markdown links reject unsafe URLs', () => {
  assert.equal(sanitizeMarkdownLink('javascript:alert(1)'), null);
  assert.equal(sanitizeMarkdownLink('java\nscript:alert(1)'), null);
  assert.equal(sanitizeMarkdownLink('data:text/html,test'), null);
  assert.equal(sanitizeMarkdownLink('//example.com'), null);
});


test('markdown images allow only local URLs', () => {
  assert.equal(sanitizeMarkdownImage('/assets/food.png'), '/assets/food.png');
  assert.equal(sanitizeMarkdownImage('images/food.png'), 'images/food.png');
  assert.equal(sanitizeMarkdownImage('https://example.com/tracker.png'), null);
  assert.equal(sanitizeMarkdownImage('htt\nps://example.com/tracker.png'), null);
  assert.equal(sanitizeMarkdownImage('data:image/svg+xml,test'), null);
});


test('external link detection is limited to HTTP links', () => {
  assert.equal(isExternalMarkdownLink('https://example.com'), true);
  assert.equal(isExternalMarkdownLink('http://example.com'), true);
  assert.equal(isExternalMarkdownLink('/history/1'), false);
  assert.equal(isExternalMarkdownLink('mailto:hello@example.com'), false);
});
