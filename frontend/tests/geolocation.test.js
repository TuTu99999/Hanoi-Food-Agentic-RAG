import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createNearbyRequestPayload,
  getGeolocationErrorMessage,
  normalizeCoordinates,
  requestCurrentLocation,
} from '../src/lib/geolocation.js';


test('normalizes only finite coordinates inside valid ranges', () => {
  assert.deepEqual(
    normalizeCoordinates({ latitude: 21.0285, longitude: 105.8542 }),
    { latitude: 21.0285, longitude: 105.8542 },
  );
  assert.equal(normalizeCoordinates({ latitude: 91, longitude: 105 }), null);
  assert.equal(normalizeCoordinates({ latitude: 21, longitude: 181 }), null);
  assert.equal(normalizeCoordinates({ latitude: '21', longitude: 105 }), null);
  assert.equal(normalizeCoordinates(null), null);
});


test('creates a nested nearby payload only for an allowed radius', () => {
  const coordinates = { latitude: 21.0285, longitude: 105.8542 };

  assert.deepEqual(createNearbyRequestPayload(coordinates, 3), {
    nearby: {
      latitude: 21.0285,
      longitude: 105.8542,
      radius_km: 3,
    },
  });
  assert.deepEqual(createNearbyRequestPayload(coordinates, 2), {});
  assert.deepEqual(createNearbyRequestPayload(null, 3), {});
});


test('requests browser location only when the helper is called', async () => {
  let callCount = 0;
  let receivedOptions;
  const geolocation = {
    getCurrentPosition: (onSuccess, _onError, options) => {
      callCount += 1;
      receivedOptions = options;
      onSuccess({
        coords: { latitude: 21.0285, longitude: 105.8542 },
      });
    },
  };

  assert.equal(callCount, 0);
  const coordinates = await requestCurrentLocation(geolocation);

  assert.equal(callCount, 1);
  assert.deepEqual(coordinates, { latitude: 21.0285, longitude: 105.8542 });
  assert.equal(receivedOptions.enableHighAccuracy, false);
  assert.equal(receivedOptions.timeout, 10000);
});


test('rejects unsupported browsers and invalid returned coordinates', async () => {
  await assert.rejects(
    requestCurrentLocation(null),
    error => error.code === 'unsupported',
  );

  await assert.rejects(
    requestCurrentLocation({
      getCurrentPosition: onSuccess => onSuccess({
        coords: { latitude: 100, longitude: 105 },
      }),
    }),
    error => error.code === 'invalid',
  );
});


test('returns accessible messages for browser geolocation errors', () => {
  assert.equal(
    getGeolocationErrorMessage({ code: 1 }),
    'Bạn chưa cấp quyền truy cập vị trí.',
  );
  assert.equal(
    getGeolocationErrorMessage({ code: 2 }),
    'Không thể xác định vị trí hiện tại của bạn.',
  );
  assert.equal(
    getGeolocationErrorMessage({ code: 3 }),
    'Xác định vị trí quá thời gian. Vui lòng thử lại.',
  );
});


test('geolocation helper does not access browser storage', async () => {
  let storageAccesses = 0;
  globalThis.window = {
    sessionStorage: {
      getItem: () => { storageAccesses += 1; },
      setItem: () => { storageAccesses += 1; },
    },
  };

  try {
    await requestCurrentLocation({
      getCurrentPosition: onSuccess => onSuccess({
        coords: { latitude: 21.0285, longitude: 105.8542 },
      }),
    });
    assert.equal(storageAccesses, 0);
  } finally {
    delete globalThis.window;
  }
});
