const apiBaseUrl = new URL(
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  window.location.origin,
).toString().replace(/\/$/, "");

export async function createSession(): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/sessions`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`创建会话失败：HTTP ${response.status}`);
  }
  const payload = (await response.json()) as { sessionId: string };
  return payload.sessionId;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${apiBaseUrl}/sessions/${sessionId}`, { method: "DELETE" });
}

export function sessionWebSocketUrl(sessionId: string): string {
  const url = new URL(`${apiBaseUrl}/sessions/${sessionId}/events`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function realtimeWebSocketUrl(sessionId: string): string {
  const url = new URL(`${apiBaseUrl}/sessions/${sessionId}/realtime`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
