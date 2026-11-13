/** The public endpoint's settings parser: defaults, precedence, and every refusal naming the variable but never its value. */
import { describe, expect, it } from "vitest";

import { readEndpointSettings, SettingsError } from "../src/http-settings.js";

const base = { OM_ROOT: "/srv/openmasonry" };

function refusal(env: Record<string, string>): SettingsError {
  try {
    readEndpointSettings(env);
  } catch (error) {
    if (error instanceof SettingsError) return error;
    throw error;
  }
  throw new Error("expected a SettingsError");
}

describe("readEndpointSettings", () => {
  it("defaults to a loopback bind on port 3000 with no lists and no body limit", () => {
    expect(readEndpointSettings(base)).toEqual({ root: "/srv/openmasonry", host: "127.0.0.1", port: 3000 });
  });

  it("prefers OM_ENGINE_HTTP_PORT to PORT and reads every list and limit", () => {
    const settings = readEndpointSettings({
      ...base, PORT: "8080", OM_ENGINE_HTTP_PORT: "0", OM_ENGINE_HTTP_HOST: "0.0.0.0",
      OM_ENGINE_HTTP_ALLOWED_HOSTS: " om.example.org , ,om.example.org:443", OM_ENGINE_HTTP_ALLOWED_ORIGINS: "https://om.example.org",
      OM_ENGINE_HTTP_MAX_BODY_BYTES: "4096",
    });
    expect(settings).toEqual({
      root: "/srv/openmasonry", host: "0.0.0.0", port: 0, hosts: ["om.example.org", "om.example.org:443"],
      origins: ["https://om.example.org"], bodyLimit: 4096,
    });
    expect(readEndpointSettings({ ...base, PORT: "8080" }).port).toBe(8080);
  });

  it("refuses what it cannot use, naming the variable and not the value", () => {
    const cases: Array<[Record<string, string>, string]> = [
      [{}, "OM_ROOT"],
      [{ ...base, OM_ENGINE_HTTP_HOST: "0.0.0.0" }, "OM_ENGINE_HTTP_ALLOWED_HOSTS"],
      [{ ...base, OM_ENGINE_HTTP_HOST: "" }, "OM_ENGINE_HTTP_HOST"],
      [{ ...base, OM_ENGINE_HTTP_HOST: "a\u0000b" }, "OM_ENGINE_HTTP_HOST"],
      [{ ...base, OM_ENGINE_HTTP_PORT: "70000" }, "OM_ENGINE_HTTP_PORT"],
      [{ ...base, OM_ENGINE_HTTP_PORT: "-1" }, "OM_ENGINE_HTTP_PORT"],
      [{ ...base, PORT: "3e3" }, "PORT"],
      [{ ...base, OM_ENGINE_HTTP_ALLOWED_HOSTS: " , " }, "OM_ENGINE_HTTP_ALLOWED_HOSTS"],
      [{ ...base, OM_ENGINE_HTTP_ALLOWED_HOSTS: "secret-value.example/path" }, "OM_ENGINE_HTTP_ALLOWED_HOSTS"],
      [{ ...base, OM_ENGINE_HTTP_ALLOWED_ORIGINS: "ftp://secret-value.example" }, "OM_ENGINE_HTTP_ALLOWED_ORIGINS"],
      [{ ...base, OM_ENGINE_HTTP_MAX_BODY_BYTES: "0" }, "OM_ENGINE_HTTP_MAX_BODY_BYTES"],
    ];
    for (const [env, name] of cases) {
      const error = refusal(env);
      expect(error.message, JSON.stringify(env)).toContain(name);
      expect(error.message).not.toContain("secret-value");
    }
  });

  it("accepts every loopback spelling without a Host allowlist", () => {
    for (const host of ["127.0.0.1", "localhost", "LOCALHOST", "::1", "[::1]"]) {
      expect(readEndpointSettings({ ...base, OM_ENGINE_HTTP_HOST: host }).host).toBe(host);
    }
  });
});
