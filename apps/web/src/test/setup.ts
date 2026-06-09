import "@testing-library/jest-dom/vitest";

if (!globalThis.window.URL.createObjectURL) {
  globalThis.window.URL.createObjectURL = () => "blob:frw-test";
}

globalThis.window.scrollTo = () => undefined;
