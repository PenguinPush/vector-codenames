import { test, expect } from "@playwright/test";

test("two independent mobile players share a room, act in their roles, and reconnect", async ({ browser }) => {
  const hostContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const guessContext = await browser.newContext({ viewport: { width: 320, height: 740 } });
  const host = await hostContext.newPage();
  const guesser = await guessContext.newPage();
  await host.goto("/");
  await host.getByRole("button", { name: "Create room" }).click();
  await expect(host).toHaveURL(/\/room\/[A-F0-9]{6}$/);
  const url = host.url();
  await host.getByLabel("Your name").fill("Ada");
  await host.getByRole("button", { name: "Play red spymaster", exact: true }).click();
  await guesser.goto(url);
  await guesser.getByLabel("Your name").fill("Lin");
  await guesser.getByRole("button", { name: "Play red guesser", exact: true }).click();
  await host.getByRole("button", { name: "Ready", exact: true }).click();
  await guesser.getByRole("button", { name: "Ready", exact: true }).click();
  await expect(host.getByRole("button", { name: "Start game" })).toBeEnabled();
  await host.getByRole("button", { name: "Start game" }).click();
  await expect(host.getByRole("heading", { name: "Make the connection." })).toBeVisible();
  await expect(guesser.getByText("Key hidden", { exact: true })).toBeVisible();
  await host.getByLabel("Clue word").fill("orbit");
  await host.getByLabel("Clue count").fill("2");
  await host.getByRole("button", { name: "Send", exact: true }).click();
  await expect(guesser.getByRole("heading", { name: "Find your words." })).toBeVisible();
  const roomCode = url.split("/").at(-1)!;
  const hostState = await (await hostContext.request.get(`/api/rooms/${roomCode}`)).json();
  const guessState = await (await guessContext.request.get(`/api/rooms/${roomCode}`)).json();
  expect(guessState.board.every((card: { kind: string | null }) => card.kind === null)).toBe(true);
  expect(guessState.analysis).toBeNull();
  const friendly = hostState.board.find((card: { kind: string }) => card.kind === "red");
  await guesser.getByTestId(`card-${friendly.id}`).click();
  await guesser.getByRole("button", { name: `Guess ${friendly.word}`, exact: true }).click();
  await expect(host.getByTestId(`card-${friendly.id}`)).toHaveAccessibleName(/revealed/);
  await guesser.reload();
  await expect(guesser.getByTestId("red-guesser").getByText("You", { exact: true })).toBeVisible();
  await expect(guesser.getByRole("button", { name: "End turn" })).toBeEnabled();
  for (const page of [host, guesser]) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await host.screenshot({ path: "test-results/mobile-spymaster.png", fullPage: true });
  await guesser.screenshot({ path: "test-results/mobile-guesser.png", fullPage: true });
  await guesser.getByRole("button", { name: "End turn" }).click();
  await expect(host.getByText("Blue", { exact: true }).first()).toBeVisible();
  await hostContext.close(); await guessContext.close();
});

test("spectators can pause and step bots; live replay is protected", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Create room" }).click();
  await page.getByRole("button", { name: "Watch red spymaster", exact: true }).click();
  await page.getByRole("button", { name: "Start game" }).click();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const code = page.url().split("/").at(-1)!;
  const replay = await page.request.get(`/api/rooms/${code}/replay`);
  expect(replay.status()).toBe(403);
  const before = await (await page.request.get(`/api/rooms/${code}`)).json();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Illustrative values, not Gemma cosine similarities.")).toBeVisible();
  const after = await (await page.request.get(`/api/rooms/${code}`)).json();
  expect(after.version).toBeGreaterThan(before.version);
  expect(after.paused).toBe(true);
  await page.screenshot({ path: "test-results/desktop-spectator.png", fullPage: true });
});
