interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly PROD: boolean;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __BUILD_TIME__: string;
declare const __BUILD_COMMIT__: string;
