import { test, expect, type Page } from "@playwright/test";
import { newSession } from "./helpers";

/**
 * A first run with no provider key, or one. The fixture's backend has keys,
 * so the browser is shown a catalogue and key status without them: what the
 * page does with those is what is tested (the backend would refuse the turn).
 */

/** Rewrite GET /models and /config/keys as if only `keyed` families had a key. */
async function withKeys(page: Page, keyed: string[]) {
  await page.route(/\/models$/, async (route) => {
    const body = await (await route.fetch()).json();
    body.families = body.families.map((f: { key: string }) => ({ ...f, available: keyed.includes(f.key) }));
    await route.fulfill({ json: body });
  });
  await page.route(/\/config\/keys$/, async (route) => {
    if (route.request().method() !== "GET") return route.abort();
    const body = await (await route.fetch()).json();
    for (const name of Object.keys(body)) {
      const family = name.split("_")[0].toLowerCase(); // OPENAI_API_KEY -> openai
      if (!keyed.includes(family)) body[name] = { ...body[name], set: false, masked: "" };
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
}

test("with no key, the landing view takes you to the key field and nothing can be sent", async ({ page }) => {
  await withKeys(page, []);
  const add = page.getByRole("button", { name: "Add an API key" });
  await expect(add).toBeVisible();
  await add.click();
  // The panel opens on API Keys, its first field focused and in view.
  const field = page.getByLabel("OpenAI API key");
  await expect(field).toBeFocused();
  await expect(field).toBeInViewport();

  // Sending used to be enabled, with a model the header showed as ready;
  // the turn failed only after it was sent.
  await newSession(page);
  await page.getByPlaceholder(/Ask the arena/i).fill("Hello?");
  const send = page.getByTestId("composer-toolbar").getByRole("button", { name: "Send" });
  await expect(send).toHaveAttribute("aria-disabled", "true");
  await expect(page.getByText(/No API key yet/)).toBeVisible();
  await send.hover();
  await expect(page.getByRole("tooltip")).toHaveText("Add an API key first: Control Panel → API Keys");
});

test("with one provider's key, the arena compares two of its models", async ({ page }) => {
  await withKeys(page, ["anthropic"]);
  await newSession(page);
  // Not a single-model chat: two of the family's models answer.
  await expect(page.getByText("2 models answer")).toBeVisible();
});
