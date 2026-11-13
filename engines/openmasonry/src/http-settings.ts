/**
 * Settings of the public HTTP endpoint, taken from the process environment.
 *
 *   OM_ROOT                         a clone of OpenMasonry (required)
 *   OM_ENGINE_HTTP_HOST             interface to bind (default 127.0.0.1)
 *   OM_ENGINE_HTTP_PORT             port (default 3000); when it is unset, PORT is used
 *   OM_ENGINE_HTTP_ALLOWED_HOSTS    Host allowlist, comma-separated; mandatory off loopback
 *   OM_ENGINE_HTTP_ALLOWED_ORIGINS  browser Origin allowlist, comma-separated (default: none)
 *   OM_ENGINE_HTTP_MAX_BODY_BYTES   largest request body (default 1 MiB)
 *
 * Nothing is guessed. A variable that is set but unusable stops startup with a
 * `SettingsError`, whose message names the variable and never echoes its value.
 */
import { bareHostname, bareOrigin, isLoopbackHost } from "./http-transport.js";

export interface EndpointSettings {
  root: string;
  host: string;
  port: number;
  hosts?: string[];
  origins?: string[];
  bodyLimit?: number;
}

export class SettingsError extends Error {
  override name = "SettingsError";
}

type Environment = Readonly<Record<string, string | undefined>>;

const HIGHEST_PORT = 65_535;

function text(env: Environment, key: string): string | undefined {
  const given = env[key];
  if (given === undefined) return undefined;
  if (given === "") throw new SettingsError(`${key} is set to an empty string; give it a value or unset it`);
  if (given.includes("\0")) throw new SettingsError(`${key} contains a NUL byte`);
  return given;
}

function wholeNumber(env: Environment, key: string, low: number, high: number): number | undefined {
  const given = text(env, key);
  if (given === undefined) return undefined;
  const n = /^\d+$/.test(given) ? Number(given) : Number.NaN;
  if (Number.isSafeInteger(n) && n >= low && n <= high) return n;
  throw new SettingsError(`${key} must be a whole number from ${low} to ${high}`);
}

function commaList(env: Environment, key: string): string[] | undefined {
  const given = text(env, key);
  if (given === undefined) return undefined;
  const items = given.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
  if (items.length > 0) return items;
  throw new SettingsError(`${key} lists nothing; give at least one entry, separated by commas`);
}

/** Reads and checks every setting, or throws the first `SettingsError`. */
export function readEndpointSettings(env: Environment): EndpointSettings {
  const root = text(env, "OM_ROOT");
  if (root === undefined) throw new SettingsError("OM_ROOT is required: point it at a clone of OpenMasonry");

  const host = text(env, "OM_ENGINE_HTTP_HOST") ?? "127.0.0.1";
  const port = wholeNumber(env, "OM_ENGINE_HTTP_PORT", 0, HIGHEST_PORT)
    ?? wholeNumber(env, "PORT", 0, HIGHEST_PORT)
    ?? 3000;
  const settings: EndpointSettings = { root, host, port };

  const hosts = commaList(env, "OM_ENGINE_HTTP_ALLOWED_HOSTS");
  if (hosts === undefined) {
    // The transport checks the raw Host header, so a public bind with no list could be reached under any name.
    if (!isLoopbackHost(host)) {
      throw new SettingsError("OM_ENGINE_HTTP_ALLOWED_HOSTS must be set when OM_ENGINE_HTTP_HOST is not a loopback address");
    }
  } else {
    if (hosts.some((entry) => bareHostname(entry) === null)) {
      throw new SettingsError("OM_ENGINE_HTTP_ALLOWED_HOSTS has an entry that is not a host name (with an optional port)");
    }
    settings.hosts = hosts;
  }

  const origins = commaList(env, "OM_ENGINE_HTTP_ALLOWED_ORIGINS");
  if (origins !== undefined) {
    if (origins.some((entry) => bareOrigin(entry) === null)) {
      throw new SettingsError("OM_ENGINE_HTTP_ALLOWED_ORIGINS has an entry that is not an http or https origin");
    }
    settings.origins = origins;
  }

  const bodyLimit = wholeNumber(env, "OM_ENGINE_HTTP_MAX_BODY_BYTES", 1, Number.MAX_SAFE_INTEGER);
  if (bodyLimit !== undefined) settings.bodyLimit = bodyLimit;
  return settings;
}
