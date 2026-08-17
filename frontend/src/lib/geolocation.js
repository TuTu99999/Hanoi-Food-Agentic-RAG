export const NEARBY_RADIUS_OPTIONS = Object.freeze([1, 3, 5, 10]);

const GEOLOCATION_OPTIONS = Object.freeze({
  enableHighAccuracy: false,
  timeout: 10000,
  maximumAge: 60000,
});

const createLocationError = (code, message) => {
  const error = new Error(message);
  error.code = code;
  return error;
};

export const normalizeCoordinates = (coordinates) => {
  const latitude = coordinates?.latitude;
  const longitude = coordinates?.longitude;

  if (
    !Number.isFinite(latitude)
    || !Number.isFinite(longitude)
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
  ) {
    return null;
  }

  return { latitude, longitude };
};

export const requestCurrentLocation = (
  geolocation = globalThis.navigator?.geolocation,
) => new Promise((resolve, reject) => {
  if (!geolocation?.getCurrentPosition) {
    reject(createLocationError(
      'unsupported',
      'Trình duyệt không hỗ trợ xác định vị trí.',
    ));
    return;
  }

  geolocation.getCurrentPosition(
    (position) => {
      const coordinates = normalizeCoordinates(position?.coords);
      if (!coordinates) {
        reject(createLocationError('invalid', 'Vị trí nhận được không hợp lệ.'));
        return;
      }
      resolve(coordinates);
    },
    reject,
    GEOLOCATION_OPTIONS,
  );
});

export const getGeolocationErrorMessage = (error) => {
  switch (error?.code) {
    case 1:
      return 'Bạn chưa cấp quyền truy cập vị trí.';
    case 2:
      return 'Không thể xác định vị trí hiện tại của bạn.';
    case 3:
      return 'Xác định vị trí quá thời gian. Vui lòng thử lại.';
    case 'unsupported':
      return 'Trình duyệt không hỗ trợ xác định vị trí.';
    case 'invalid':
      return 'Vị trí nhận được không hợp lệ.';
    default:
      return 'Không thể lấy vị trí hiện tại. Vui lòng thử lại.';
  }
};

export const createNearbyRequestPayload = (coordinates, radiusKm) => {
  const normalizedCoordinates = normalizeCoordinates(coordinates);
  const normalizedRadius = Number(radiusKm);

  if (
    !normalizedCoordinates
    || !NEARBY_RADIUS_OPTIONS.includes(normalizedRadius)
  ) {
    return {};
  }

  return {
    nearby: {
      ...normalizedCoordinates,
      radius_km: normalizedRadius,
    },
  };
};
