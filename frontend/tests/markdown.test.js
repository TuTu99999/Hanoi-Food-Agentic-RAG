import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isExternalMarkdownLink,
  isGoogleMapsDirectionsLink,
  placeDirectionsNextToVenues,
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


test('markdown images allow local and Wikimedia URLs', () => {
  assert.equal(sanitizeMarkdownImage('/assets/food.png'), '/assets/food.png');
  assert.equal(sanitizeMarkdownImage('images/food.png'), 'images/food.png');
  assert.equal(
    sanitizeMarkdownImage('https://upload.wikimedia.org/example.jpg'),
    'https://upload.wikimedia.org/example.jpg',
  );
  assert.equal(sanitizeMarkdownImage('https://example.com/tracker.png'), null);
  assert.equal(sanitizeMarkdownImage('http://upload.wikimedia.org/example.jpg'), null);
  assert.equal(sanitizeMarkdownImage('https://upload.wikimedia.org.evil.test/example.jpg'), null);
  assert.equal(sanitizeMarkdownImage('https://evil.test@upload.wikimedia.org/example.jpg'), null);
  assert.equal(sanitizeMarkdownImage('htt\nps://example.com/tracker.png'), null);
  assert.equal(sanitizeMarkdownImage('data:image/svg+xml,test'), null);
});


test('external link detection is limited to HTTP links', () => {
  assert.equal(isExternalMarkdownLink('https://example.com'), true);
  assert.equal(isExternalMarkdownLink('http://example.com'), true);
  assert.equal(isExternalMarkdownLink('/history/1'), false);
  assert.equal(isExternalMarkdownLink('mailto:hello@example.com'), false);
});


test('Google Maps directions links require the expected secure URL', () => {
  assert.equal(
    isGoogleMapsDirectionsLink(
      'https://www.google.com/maps/dir/?api=1&destination=21.03%2C105.81',
    ),
    true,
  );
  assert.equal(
    isGoogleMapsDirectionsLink(
      'https://www.google.com/maps/dir/?api=1&destination=149+%C4%90%C6%B0%E1%BB%9Dng+%C4%90%C3%AA+La+Th%C3%A0nh%2C+H%C3%A0+N%E1%BB%99i',
    ),
    true,
  );
  assert.equal(
    isGoogleMapsDirectionsLink(
      'https://www.google.com.evil.test/maps/dir/?api=1&destination=21.03%2C105.81',
    ),
    false,
  );
  assert.equal(
    isGoogleMapsDirectionsLink(
      'https://www.google.com/maps/dir/?api=1&destination=invalid',
    ),
    false,
  );
  assert.equal(
    isGoogleMapsDirectionsLink(
      'https://evil.test@www.google.com/maps/dir/?api=1&destination=21.03%2C105.81',
    ),
    false,
  );
});


test('directions links are placed directly below their venues', () => {
  const firstUrl = 'https://www.google.com/maps/dir/?api=1&destination=149+%C4%90%C3%AA+La+Th%C3%A0nh%2C+H%C3%A0+N%E1%BB%99i';
  const secondUrl = 'https://www.google.com/maps/dir/?api=1&destination=10+Trung+K%C3%ADnh%2C+C%E1%BA%A7u+Gi%E1%BA%A5y%2C+H%C3%A0+N%E1%BB%99i';
  const content = [
    '**Phở Bò 149**',
    'Địa chỉ: 149 Đê La Thành, Hà Nội',
    'Giờ mở cửa: chưa có dữ liệu',
    '',
    '**Phở Trung Kính**',
    'Địa chỉ: 10 Trung Kính, Cầu Giấy, Hà Nội',
    '',
    '**Chỉ đường từ vị trí hiện tại:**',
    `- [Phở Bò 149 — 149 Đê La Thành, Hà Nội](${firstUrl})`,
    `- [Phở Trung Kính — 10 Trung Kính, Cầu Giấy, Hà Nội](${secondUrl})`,
  ].join('\n');

  const result = placeDirectionsNextToVenues(content);

  assert.equal(result.includes('**Chỉ đường từ vị trí hiện tại:**'), false);
  assert.ok(result.indexOf(firstUrl) > result.indexOf('149 Đê La Thành'));
  assert.ok(result.indexOf(firstUrl) < result.indexOf('Giờ mở cửa'));
  assert.ok(result.indexOf(secondUrl) > result.indexOf('10 Trung Kính'));
});
