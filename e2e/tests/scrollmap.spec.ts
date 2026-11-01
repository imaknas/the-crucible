import { test, expect, type Page } from "@playwright/test";
import { newSession, openApp, send } from "./helpers";

/**
 * The scroll map beside the transcript: one marker per message, drawn where
 * the scrollbar thumb sits when that message is at the top, and a click jumps
 * there. Its placement was tuned by hand (ChatView `updateMarkers`), so these
 * pin the behaviour rather than the formula's constants.
 */

const QUESTIONS = ["First question", "Second question", "Third question", "Fourth question", "Fifth question"];

/** The transcript's scroll container and the scroll map's geometry. */
async function geometry(page: Page) {
  return page.evaluate(() => {
    const nav = document.querySelector('nav[aria-label="Jump to a message"]') as HTMLElement;
    const scroller = [...(nav.parentElement as HTMLElement).children].find(
      (el) => el !== nav && el.scrollHeight > el.clientHeight + 1,
    ) as HTMLElement;
    const navTop = nav.getBoundingClientRect().top;
    const markers = [...nav.querySelectorAll("button")].map((b) => b.getBoundingClientRect().top - navTop);
    return {
      scrollTop: scroller.scrollTop,
      maxScroll: scroller.scrollHeight - scroller.clientHeight,
      clientHeight: scroller.clientHeight,
      scrollHeight: scroller.scrollHeight,
      scrollerTop: scroller.getBoundingClientRect().top,
      markers,
    };
  });
}

/** The transcript beside the scroll map (the sidebar lists the same titles). */
function transcript(page: Page) {
  return page.getByRole("navigation", { name: "Jump to a message" }).locator("xpath=..");
}

/** Wait for a smooth scroll to come to rest. */
async function scrollSettled(page: Page) {
  let previous = -1;
  for (let i = 0; i < 40; i++) {
    const { scrollTop } = await geometry(page);
    if (Math.abs(scrollTop - previous) < 0.5) return;
    previous = scrollTop;
    await page.waitForTimeout(100);
  }
}

test.describe("scroll map", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
    await newSession(page);
    for (const [i, question] of QUESTIONS.entries()) {
      await send(page, question);
      await expect(page.getByText(/Scripted answer from gpt-6\.1-sol/)).toHaveCount(i + 1);
    }
    // The last reply has finished streaming (Send is back in place of Stop).
    await expect(page.getByTestId("composer-toolbar").getByText("Send", { exact: true })).toBeVisible();
  });

  test("has one marker per message, in transcript order", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Jump to a message" });
    const markers = nav.getByRole("button");
    await expect(markers).toHaveCount(QUESTIONS.length * 2);
    await expect(markers.first()).toHaveAccessibleName(`Your message 1 of ${QUESTIONS.length * 2}`);
    await expect(markers.nth(1)).toHaveAccessibleName(`Reply 2 of ${QUESTIONS.length * 2}`);

    const { markers: tops, scrollHeight, clientHeight } = await geometry(page);
    expect(scrollHeight).toBeGreaterThan(clientHeight); // the transcript really scrolls
    for (let i = 1; i < tops.length; i++) expect(tops[i]).toBeGreaterThanOrEqual(tops[i - 1]);
  });

  test("a marker jumps to its message and sits where the thumb lands", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Jump to a message" });
    const total = QUESTIONS.length * 2;

    for (const index of [0, 4, 2]) {
      // Your message `index + 1`: the question QUESTIONS[index / 2].
      await nav.getByRole("button", { name: `Your message ${index + 1} of ${total}` }).click();
      await scrollSettled(page);
      const g = await geometry(page);

      const question = transcript(page).getByText(QUESTIONS[index / 2], { exact: true });
      await expect(question).toBeInViewport();
      if (g.scrollTop < g.maxScroll - 1) {
        // Not clamped at the bottom: the message is at the top of the transcript.
        const top = (await question.boundingBox())!.y - g.scrollerTop;
        expect(top).toBeGreaterThanOrEqual(-2);
        expect(top).toBeLessThan(80);
      }

      // The marker sits where the scrollbar thumb's top now is.
      const thumb = Math.max((g.clientHeight * g.clientHeight) / g.scrollHeight, 30);
      const thumbTop = (g.scrollTop / g.maxScroll) * (g.clientHeight - thumb);
      expect(Math.abs(g.markers[index] - thumbTop)).toBeLessThan(3);
    }
  });

  test("the last marker scrolls to the bottom", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Jump to a message" });
    await nav.getByRole("button", { name: "Your message 1 of 10" }).click();
    await scrollSettled(page);
    const top = await geometry(page);
    expect(top.scrollTop).toBeLessThan(top.maxScroll / 4);
    await expect(transcript(page).getByText(QUESTIONS[0], { exact: true })).toBeInViewport();

    await nav.getByRole("button", { name: "Reply 10 of 10" }).click();
    await scrollSettled(page);
    const g = await geometry(page);
    expect(g.maxScroll - g.scrollTop).toBeLessThan(2);
    await expect(page.getByText(/Scripted answer from gpt-6\.1-sol/).last()).toBeInViewport();
  });

  test("a marker jumps even while a reply is still streaming", async ({ page }) => {
    // While a reply streams at the bottom the view follows its tokens. At the
    // scripted model's normal pace (a token every 40ms, ~1.2s per reply) the
    // next token used to snap the view back before the smooth scroll had left
    // the bottom, so the jump was undone. ([[slow]] tokens are too far apart
    // to show it.)
    await send(page, "Keep talking");
    await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Jump to a message" });
    await nav.getByRole("button", { name: /^Your message 1 of / }).click();
    await expect(page.getByTestId("composer-toolbar").getByText("Send", { exact: true })).toBeVisible();
    await scrollSettled(page);
    await expect(transcript(page).getByText(QUESTIONS[0], { exact: true })).toBeInViewport();
    const g = await geometry(page);
    expect(g.scrollTop).toBeLessThan(g.maxScroll / 4);
  });
});
