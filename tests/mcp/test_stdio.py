"""Check a real subprocess; AURORA_MCP_EXECUTABLE selects the Nix wrapper."""
import asyncio
import os
from pathlib import Path
import sys
import unittest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError


class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_protocol_refusal_and_cleanup(self):
        executable = os.environ.get('AURORA_MCP_EXECUTABLE')
        transport = StdioTransport(
            command=executable or sys.executable,
            args=[] if executable else [str(Path(__file__).resolve().parents[2] / 'mcp/aurora_mcdbus.py')],
            keep_alive=False)
        async with asyncio.timeout(20):
            async with Client(transport) as client:
                tools = {tool.name for tool in await client.list_tools()}
                self.assertEqual(tools, {'describe_object', 'call_method', 'set_property'})
                # Invalid endpoints must stop before opening any bus connection.
                with self.assertRaisesRegex(ToolError, 'Invalid bus or well-known service name'):
                    await client.call_tool('describe_object', {
                        'bus': 'invalid', 'service': 'org.kde.Test', 'object_path': '/'})
            self.assertIsNone(transport._connect_task)
            self.assertIsNone(transport._session)


if __name__ == '__main__':
    unittest.main()
