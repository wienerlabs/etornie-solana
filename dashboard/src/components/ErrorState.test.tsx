import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ErrorState from "./ErrorState";

describe("ErrorState", () => {
  it("renders the title and message", () => {
    render(<ErrorState title="Boom" message="It broke" />);
    expect(screen.getByText("Boom")).toBeInTheDocument();
    expect(screen.getByText("It broke")).toBeInTheDocument();
  });

  it("shows a retry button that calls onRetry when clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("hides the retry button when no handler is provided", () => {
    render(<ErrorState />);
    expect(
      screen.queryByRole("button", { name: /try again/i })
    ).toBeNull();
  });
});
