const basePath = import.meta.env.BASE_URL || "/";

function isAbsoluteUrl(value: string): boolean {
  return /^[a-z][a-z\d+.-]*:/i.test(value) || value.startsWith("//");
}

export function appPath(value: string): string {
  if (isAbsoluteUrl(value)) return value;

  const path = `/${value.replace(/^\/+/, "")}`;
  if (basePath === "/" || path.startsWith(basePath)) return path;
  return `${basePath}${path.slice(1)}`;
}

export function appUrl(value: string): URL {
  return new URL(appPath(value), window.location.origin);
}
