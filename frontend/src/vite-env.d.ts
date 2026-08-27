/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where the backend is. Defaults to the loopback address `hbl serve` binds
   * to, so a developer needs no `.env` at all.
   *
   * Set it when the API runs on the GPU workstation and the browser does not:
   * `VITE_API_BASE=http://192.168.1.40:8000`. It must stay on the local
   * network — the backend refuses a public model endpoint for the same reason,
   * and questions about bank policy should not cross one either.
   */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
