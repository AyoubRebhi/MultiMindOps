"""
DevSecOps MCP Server package.

Usage — start the server:
    python -m mcp.server

Usage — from backend:
    from backend.app.services.mcp_client import MCPClient
    client = MCPClient.get_instance()
    result = client.query_resource("aws://terraform/resource/aws_vpc")
"""

__version__ = "1.0.0"
