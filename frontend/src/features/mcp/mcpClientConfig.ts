// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The client configuration a person pastes into their AI client.
 *
 * Most MCP clients read a `mcpServers` map whose entries name a transport,
 * a URL and extra headers; the token travels as a Bearer header. The snippet is
 * built here rather than by the server so it carries the origin the person is
 * actually using (a reverse proxy may rename the host the server sees).
 */
import { MCP_ENDPOINT_PATH } from './api';

export const MCP_SERVER_KEY = 'openconstructionerp';
/** Placeholder shown when the secret is no longer available (it is returned only once). */
export const TOKEN_PLACEHOLDER = '<your-token>';

/** Absolute endpoint URL for `origin` (no trailing slash on the origin). */
export function mcpEndpointUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}${MCP_ENDPOINT_PATH}`;
}

/** Pretty-printed JSON for the client's MCP server list. */
export function buildClientConfig(origin: string, token: string | null | undefined): string {
  const config = {
    mcpServers: {
      [MCP_SERVER_KEY]: {
        type: 'http',
        url: mcpEndpointUrl(origin),
        headers: { Authorization: `Bearer ${token || TOKEN_PLACEHOLDER}` },
      },
    },
  };
  return JSON.stringify(config, null, 2);
}

/** A one-line handshake check a person can run in a terminal. */
export function buildHandshakeCheck(origin: string, token: string | null | undefined): string {
  const body = JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'check', version: '1' } },
  });
  return (
    `curl -s -X POST ${mcpEndpointUrl(origin)} -H "Authorization: Bearer ${token || TOKEN_PLACEHOLDER}" ` +
    `-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '${body}'`
  );
}
