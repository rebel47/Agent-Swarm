import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "./tests", fullyParallel: false, workers: 1, timeout: 45000,
  expect: {timeout: 12000}, reporter: "list",
  use: {baseURL: process.env.UI_BASE_URL || "http://localhost:3000", viewport: {width: 1440, height: 1000},
    browserName: "chromium", trace: "retain-on-failure", screenshot: "only-on-failure"},
});
