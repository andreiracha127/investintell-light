// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { SelectionDiagnostics } from "./SelectionDiagnostics";

afterEach(cleanup);

const selection = {
  n_candidates: 120,
  n_selected: 3,
  excluded: [{ fund: "fund:AAA", reason: "median pairwise overlap 80 < 252" }],
  clusters: { "fund:REP1": 1, "fund:REP2": 2, "fund:REP3": 3 },
};

describe("SelectionDiagnostics", () => {
  it("summarises candidates→positions and expands to clusters + exclusions", async () => {
    const user = userEvent.setup();
    render(<SelectionDiagnostics selection={selection} />);

    // Summary visible while collapsed; detail tables hidden.
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/candidates/)).toBeInTheDocument();
    expect(screen.queryByText("Risk cluster")).not.toBeInTheDocument();
    expect(screen.queryByText(/Excluded/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Selection/i }));

    expect(screen.getByText("Risk cluster")).toBeInTheDocument();
    expect(screen.getByText("fund:REP1")).toBeInTheDocument();
    expect(screen.getByText(/median pairwise overlap/)).toBeInTheDocument();
  });

  it("omits the excluded table when nothing was excluded", async () => {
    const user = userEvent.setup();
    render(<SelectionDiagnostics selection={{ ...selection, excluded: [] }} />);
    await user.click(screen.getByRole("button", { name: /Selection/i }));
    expect(screen.queryByText(/Excluded/)).not.toBeInTheDocument();
    expect(screen.getByText("Risk cluster")).toBeInTheDocument();
  });
});
