import "@testing-library/jest-dom/vitest";

if (!window.URL.createObjectURL) {
  window.URL.createObjectURL = () => "blob:frw-test";
}

window.scrollTo = () => undefined;
