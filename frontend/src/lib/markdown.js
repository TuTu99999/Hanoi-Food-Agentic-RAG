const URL_SCHEME = /^[a-z][a-z\d+.-]*:/i;
const SAFE_LINK_SCHEMES = new Set(['http:', 'https:', 'mailto:']);
const SAFE_IMAGE_HOSTS = new Set(['upload.wikimedia.org']);
const URL_CONTROL_CHARACTERS = /[\u0000-\u0020]/g;
const GOOGLE_MAPS_DIRECTIONS_PATH = '/maps/dir/';
const COORDINATES = /^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$/;
const DESTINATION_CONTROL_CHARACTERS = /[\u0000-\u001f]/;
const DIRECTIONS_SECTION = '\n\n**Chỉ đường từ vị trí hiện tại:**';

const cleanUrl = (url) => {
  if (typeof url !== 'string') {
    return null;
  }

  const value = url.trim();
  if (!value || value.startsWith('//') || value.startsWith('\\\\')) {
    return null;
  }

  return value;
};

export const sanitizeMarkdownLink = (url) => {
  const value = cleanUrl(url);
  if (!value) {
    return value;
  }

  const normalizedValue = value.replace(URL_CONTROL_CHARACTERS, '');
  if (normalizedValue.startsWith('//') || normalizedValue.startsWith('\\\\')) {
    return null;
  }
  if (!URL_SCHEME.test(normalizedValue)) {
    return normalizedValue;
  }

  try {
    const parsedUrl = new URL(normalizedValue);
    return SAFE_LINK_SCHEMES.has(parsedUrl.protocol) ? normalizedValue : null;
  } catch {
    return null;
  }
};

export const sanitizeMarkdownImage = (url) => {
  const value = cleanUrl(url);
  const normalizedValue = value?.replace(URL_CONTROL_CHARACTERS, '');
  if (!value) {
    return null;
  }

  if (!URL_SCHEME.test(normalizedValue)) {
    return value;
  }

  try {
    const parsedUrl = new URL(normalizedValue);
    if (parsedUrl.protocol !== 'https:' || parsedUrl.username || parsedUrl.password) {
      return null;
    }
    return SAFE_IMAGE_HOSTS.has(parsedUrl.hostname) ? normalizedValue : null;
  } catch {
    return null;
  }
};

export const isExternalMarkdownLink = (url) => /^https?:\/\//i.test(url || '');

export const isGoogleMapsDirectionsLink = (url) => {
  const safeUrl = sanitizeMarkdownLink(url);
  if (!safeUrl || !isExternalMarkdownLink(safeUrl)) {
    return false;
  }

  try {
    const parsedUrl = new URL(safeUrl);
    const destination = parsedUrl.searchParams.get('destination') || '';
    const [latitude, longitude] = destination.split(',').map(Number);
    const hasSafeDestination = destination.trim().length >= 3
      && destination.length <= 500
      && !DESTINATION_CONTROL_CHARACTERS.test(destination);
    const isCoordinates = COORDINATES.test(destination);
    const hasValidCoordinates = isCoordinates && (
      Number.isFinite(latitude)
      && Number.isFinite(longitude)
      && latitude >= -90
      && latitude <= 90
      && longitude >= -180
      && longitude <= 180
    );
    const hasValidAddress = !isCoordinates
      && destination.includes(',')
      && destination.trim().split(/\s+/).length >= 3;

    return parsedUrl.protocol === 'https:'
      && parsedUrl.hostname === 'www.google.com'
      && !parsedUrl.username
      && !parsedUrl.password
      && parsedUrl.pathname === GOOGLE_MAPS_DIRECTIONS_PATH
      && parsedUrl.searchParams.get('api') === '1'
      && hasSafeDestination
      && (hasValidCoordinates || hasValidAddress);
  } catch {
    return false;
  }
};

export const placeDirectionsNextToVenues = (content) => {
  if (typeof content !== 'string') {
    return '';
  }

  const sectionIndex = content.lastIndexOf(DIRECTIONS_SECTION);
  if (sectionIndex < 0) {
    return content;
  }

  let answer = content.slice(0, sectionIndex).trimEnd();
  const directionLines = content
    .slice(sectionIndex + DIRECTIONS_SECTION.length)
    .trim()
    .split('\n');
  const insertions = [];
  const unmatchedLines = [];

  for (const line of directionLines) {
    const match = line.match(/^-\s+\[(.+)\]\((https:\/\/[^\s)]+)\)\s*$/);
    if (!match || !isGoogleMapsDirectionsLink(match[2])) {
      if (line.trim()) unmatchedLines.push(line);
      continue;
    }

    const label = match[1].replace(/\\([\[\]\\])/g, '$1');
    const [title, ...addressParts] = label.split(' — ');
    const address = addressParts.join(' — ');
    const target = [address, title]
      .map(value => value.trim())
      .find(value => findCaseInsensitive(answer, value) >= 0);

    if (!target) {
      unmatchedLines.push(line);
      continue;
    }

    const targetIndex = findCaseInsensitive(answer, target);
    const nextLineBreak = answer.indexOf('\n', targetIndex + target.length);
    const insertionIndex = nextLineBreak >= 0 ? nextLineBreak : answer.length;
    insertions.push({
      index: insertionIndex,
      markdown: `\n\n[Chỉ đường trên Google Maps](${match[2]})`,
    });
  }

  insertions
    .sort((left, right) => right.index - left.index)
    .forEach(({ index, markdown }) => {
      answer = `${answer.slice(0, index)}${markdown}${answer.slice(index)}`;
    });

  if (unmatchedLines.length > 0) {
    answer += `${DIRECTIONS_SECTION}\n${unmatchedLines.join('\n')}`;
  }

  return answer;
};

const findCaseInsensitive = (content, value) => {
  if (!value) return -1;
  return content.toLocaleLowerCase('vi').indexOf(value.toLocaleLowerCase('vi'));
};
