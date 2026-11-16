const apiBaseUrl = new URL(
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  window.location.origin,
).toString().replace(/\/$/, "");

export async function createSession(clientId: string): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clientId }),
  });
  if (!response.ok) {
    throw new Error(`创建会话失败：HTTP ${response.status}`);
  }
  const payload = (await response.json()) as { sessionId: string };
  return payload.sessionId;
}

export async function deleteSession(
  sessionId: string,
  keepalive = false,
): Promise<void> {
  await fetch(`${apiBaseUrl}/sessions/${sessionId}`, {
    method: "DELETE",
    keepalive,
  });
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

export interface ConversationAccessStatus {
  onlineClients: number;
  conversationActive: boolean;
  conversationInProgress: boolean;
  conversationReclaimable: boolean;
  conversationInactiveSeconds: number;
  ownsConversation: boolean;
}

export function presenceWebSocketUrl(clientId: string): string {
  const url = new URL(
    `${apiBaseUrl}/access/presence/${encodeURIComponent(clientId)}`,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

async function accessRequest(
  clientId: string,
  method: "POST" | "PUT" | "DELETE",
  keepalive = false,
  suffix = "",
  body?: unknown,
): Promise<ConversationAccessStatus> {
  const response = await fetch(
    `${apiBaseUrl}/access/conversation/${encodeURIComponent(clientId)}${suffix}`,
    {
      method,
      keepalive,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? `请求失败：HTTP ${response.status}`);
  }
  return (await response.json()) as ConversationAccessStatus;
}

export function acquireConversation(
  clientId: string,
): Promise<ConversationAccessStatus> {
  return accessRequest(clientId, "POST");
}

export function releaseConversation(
  clientId: string,
  keepalive = false,
): Promise<ConversationAccessStatus> {
  return accessRequest(clientId, "DELETE", keepalive);
}

export function bindConversationAvatarSession(
  clientId: string,
  avatarSessionId: string,
): Promise<ConversationAccessStatus> {
  return accessRequest(
    clientId,
    "PUT",
    false,
    `/avatar/${encodeURIComponent(avatarSessionId)}`,
  );
}

export function reclaimInactiveConversation(
  clientId: string,
): Promise<ConversationAccessStatus> {
  return accessRequest(clientId, "POST", false, "/reclaim");
}
