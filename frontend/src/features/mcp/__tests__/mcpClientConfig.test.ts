// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  MCP_SERVER_KEY,
  TOKEN_PLACEHOLDER,
  buildClientConfig,
  buildHandshakeCheck,
  mcpEndpointUrl,
} from '../mcpClientConfig';

describe('mcpClientConfig', () => {
  it('builds the endpoint from the origin without doubling slashes', () => {
    expect(mcpEndpointUrl('https://erp.example.com/')).toBe('https://erp.example.com/api/v1/mcp');
    expect(mcpEndpointUrl('http://127.0.0.1:8000')).toBe('http://127.0.0.1:8000/api/v1/mcp');
  });

  it('puts the token in a Bearer header of an http server entry', () => {
    const parsed = JSON.parse(buildClientConfig('https://erp.example.com', 'oe_secret'));
    const entry = parsed.mcpServers[MCP_SERVER_KEY];
    expect(entry.type).toBe('http');
    expect(entry.url).toBe('https://erp.example.com/api/v1/mcp');
    expect(entry.headers.Authorization).toBe('Bearer oe_secret');
  });

  it('falls back to a placeholder once the secret is gone', () => {
    const parsed = JSON.parse(buildClientConfig('https://erp.example.com', null));
    expect(parsed.mcpServers[MCP_SERVER_KEY].headers.Authorization).toBe(`Bearer ${TOKEN_PLACEHOLDER}`);
  });

  it('writes a handshake check that posts initialize with the token', () => {
    const cmd = buildHandshakeCheck('https://erp.example.com', 'oe_secret');
    expect(cmd).toContain('https://erp.example.com/api/v1/mcp');
    expect(cmd).toContain('Bearer oe_secret');
    expect(cmd).toContain('"method":"initialize"');
  });
});
