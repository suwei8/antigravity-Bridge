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
    
    def __init__(self, telegram_func: Optional[Callable[[str, str], Optional[Exception]]] = None,
                 stdout_stream=None):
        """
        Initialize the MCP server.
        
        Args:
            telegram_func: Callback function to send Telegram messages.
                          Signature: (chat_id: str, text: str) -> Optional[Exception]
            stdout_stream: The stdout stream to use for MCP output.
                          If None, uses sys.stdout.
        """
        self.telegram_func = telegram_func
        self._output_lock = threading.Lock()
        # Use provided stdout or fall back to sys.stdout
        self._stdout = stdout_stream if stdout_stream is not None else sys.stdout
    
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
        # 确保 params 始终是字典（修复 params: null 的情况）
        params = request.get('params') or {}
        
        # 详细日志记录收到的请求
        logger.debug(f"MCP Request: method={method}, id={request_id}, params={params}")
        
        # JSON-RPC 2.0: 通知（Notification）没有 id 字段，不应返回任何响应
        # MCP 协议: 所有 notifications/ 开头的方法都是通知
        if request_id is None or method.startswith('notifications/'):
            # 这是一个通知，直接忽略，不返回任何响应
            logger.debug(f"MCP: Ignoring notification: {method}")
            return
        
        response: Dict[str, Any] = {
            'jsonrpc': '2.0',
            'id': request_id
        }
        
        try:
            if method == 'initialize':
                # 严格按照 MCP 协议规范返回
                response['result'] = {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {
                        'tools': {
                            'listChanged': False  # 明确声明不支持动态工具列表变更通知
                        },
                    },
                    'serverInfo': {
                        'name': 'antigravity-bridge',
                        'version': '2.0.0',
                    },
                }
            
            elif method == 'ping':
                # 支持 ping 请求（协议要求）
                response['result'] = {}
                
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
            self._stdout.write(message + '\n')
            self._stdout.flush()
