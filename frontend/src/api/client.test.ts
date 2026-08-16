import { ApiError, api } from "./client";

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("posts JSON control payloads", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ success: true }), { status: 200 }));
    await api.volume("12345", 48);
    expect(fetchMock).toHaveBeenCalledWith("/api/volume", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ did: "12345", volume: 48 }),
      headers: expect.objectContaining({ "Content-Type": "application/json" }),
    }));
  });

  it("surfaces backend error messages", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: "Speaker not found" }), { status: 404 }));
    await expect(api.pause("missing")).rejects.toEqual(expect.objectContaining<ApiError>({
      name: "ApiError",
      message: "Speaker not found",
      status: 404,
    }));
  });
});
