import { afterEach, describe, expect, it, vi } from "vitest";
import { request, isCorrect, percent } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("workbench transport", () => {
  it("preserves decimal strings and sends the local client header", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ id: "saved" }) });
    vi.stubGlobal("fetch", fetcher);
    await request("/corrections", { unit_price: "10.0000" });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/corrections",
      expect.objectContaining({
        method: "POST",
        body: '{"unit_price":"10.0000"}',
        headers: expect.objectContaining({
          "X-SkillFoundry-Client": "workbench",
        }),
      }),
    );
  });
  it("surfaces a stale revision without pretending to save", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          json: async () => ({ detail: "Revision conflict" }),
        }),
    );
    await expect(request("/corrections", {})).rejects.toThrow(
      "Revision conflict",
    );
  });
  it("distinguishes correct abstention from a wrong review", () => {
    expect(isCorrect("correct_review")).toBe(true);
    expect(isCorrect("wrong_review")).toBe(false);
    expect(isCorrect("critical_wrong_factor")).toBe(false);
  });
  it("does not label an empty suite as zero percent accuracy", () => {
    expect(percent(0, 0)).toBe("Not measured");
    expect(percent(31, 38)).toBe("81.6%");
  });
});
