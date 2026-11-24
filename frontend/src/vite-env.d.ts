/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BASE_PATH?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AVATAR_ID?: string;
  readonly VITE_AVATAR_IDLE_IMAGE?: string;
  readonly VITE_STUN_URL?: string;
  readonly VITE_TURN_URL?: string;
  readonly VITE_TURN_USERNAME?: string;
  readonly VITE_TURN_PASSWORD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
