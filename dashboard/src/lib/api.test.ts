import { describe, it, expect } from "vitest";
import { extractErrorMessage } from "./api";

describe("extractErrorMessage", () => {
  it("returns a string detail directly", () => {
    expect(
      extractErrorMessage({ response: { data: { detail: "Not allowed" } } })
    ).toBe("Not allowed");
  });

  it("formats a FastAPI validation-error array with field paths", () => {
    const err = {
      response: {
        data: {
          detail: [
            { loc: ["body", "email"], msg: "invalid email" },
            { loc: ["body", "password"], msg: "too short" },
          ],
        },
      },
    };
    expect(extractErrorMessage(err)).toBe(
      "email: invalid email; password: too short"
    );
  });

  it("falls back to the error message, then the provided fallback", () => {
    expect(extractErrorMessage({ message: "network down" })).toBe(
      "network down"
    );
    expect(extractErrorMessage({}, "Request failed.")).toBe("Request failed.");
  });
});
