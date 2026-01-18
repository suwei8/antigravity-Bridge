"""
MCP (Model Context Protocol) Server for Antigravity-Bridge

Implements a JSON-RPC 2.0 server over stdio for tool communication.
Supports: initialize, tools/list, tools/call methods.
"""

import json
import logging
import sys
import threading
from typing import Any, Callable, Dict, Optional

# Configure logging to stderr (stdout is for MCP protocol)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class MCPServer:
    """
    Minimal MCP Protocol server implementation.
    
    Handles JSON-RPC 2.0 over stdio for AI assistant tool integration.
    """
    
    def __init__(self, telegram_func: Optional[Callable[[str, str], Optional[Exception]]] = None):
        """
        Initialize the MCP server.
        
        Args:
            telegram_func: Callback function to send Telegram messages.
                          Signature: (chat_id: str, text: str) -> Optional[Exception]
        """
        self.telegram_func = telegram_func
        self._output_lock = threading.Lock()
    
    def start(self):
        """
        Start the stdio listener.
        
        NOTE: This blocks, so run in a thread or as main loop.
        All logs MUST go to stderr because stdout is used for protocol.
        """
        logger.info("MCP Server starting on stdio...")
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                request = json.loads(line)
                # Handle request in a thread
                thread = threading.Thread(
                    target=self._handle_request,
                    args=(request,),
                    daemon=True
                )
                thread.start()
            except json.JSONDecodeError as e:
                logger.error(f"MCP: Error parsing JSON: {e}")
                continue
    
    def _handle_request(self, request: Dict[str, Any]):
        """Handle a single JSON-RPC request."""
        method = request.get('method', '')
        request_id = request.get('id')
        params = request.get('params', {})
        
        response: Dict[str, Any] = {
            'jsonrpc': '2.0',
            'id': request_id
        }
        
        try:
            if method == 'initialize':
                response['result'] = {
                    'protocolVersion': '2024-11-05',
                    'serverInfo': {
                        'name': 'gravity-bridge',
                        'version': '2.0.0',  # Python version
                    },
                    'capabilities': {
                        'tools': {},
                    },
                }
                
            elif method == 'tools/list':
                response['result'] = {
                    'tools': [
                        {
                            'name': 'reply_to_telegram',
                            'description': 'Send a message reply to a Telegram Chat ID',
                            'inputSchema': {
                                'type': 'object',
                                'properties': {
                                    'chat_id': {
                                        'type': 'string',
                                        'description': 'The Telegram Chat ID to reply to',
                                    },
                                    'text': {
                                        'type': 'string',
                                        'description': 'The content of the message',
                                    },
                                },
                                'required': ['chat_id', 'text'],
                            },
                        },
                    ],
                }
                
            elif method == 'tools/call':
                tool_name = params.get('name', '')
                arguments = params.get('arguments', {})
                
                if tool_name == 'reply_to_telegram':
                    chat_id = arguments.get('chat_id', '')
                    text = arguments.get('text', '')
                    
                    logger.info(f"MCP: Calling reply_to_telegram({chat_id}, {text})")
                    
                    if self.telegram_func:
                        error = self.telegram_func(chat_id, text)
                        if error:
                            response['error'] = {
                                'code': -32000,
                                'message': f'Telegram Error: {error}',
                            }
                        else:
                            response['result'] = {
                                'content': [
                                    {
                                        'type': 'text',
                                        'text': 'Message sent successfully',
                                    },
                                ],
                            }
                    else:
                        response['error'] = {
                            'code': -32000,
                            'message': 'Telegram function not initialized',
                        }
                else:
                    response['error'] = {
                        'code': -32601,
                        'message': 'Tool not found',
                    }
                    
            elif method == 'notifications/initialized':
                # Notification, no response needed
                return
                
            else:
                response['error'] = {
                    'code': -32601,
                    'message': f'Method not found: {method}',
                }
                
        except Exception as e:
            logger.error(f"MCP: Error handling request: {e}")
            response['error'] = {
                'code': -32603,
                'message': f'Internal error: {str(e)}',
            }
        
        # Send response
        self._write_output(json.dumps(response))
    
    def _write_output(self, message: str):
        """Thread-safe write to stdout."""
        with self._output_lock:
            print(message, flush=True)
