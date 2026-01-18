#!/usr/bin/env python3
"""
Telegram MCP Server - 通过 Telegram Bot API 发送消息

这是一个独立的 MCP 服务器，提供发送 Telegram 消息的工具。
"""

import json
import os
import sys
import urllib.request
import urllib.error

from dotenv import load_dotenv

# 加载 .env 文件
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path)

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DEFAULT_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')


def send_telegram_message(chat_id: str, text: str) -> dict:
    """发送 Telegram 消息"""
    if not BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN 未设置"}
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            return {"success": True, "message_id": result.get("result", {}).get("message_id")}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def handle_request(request: dict) -> dict:
    """处理 MCP 请求"""
    method = request.get('method', '')
    request_id = request.get('id')
    params = request.get('params', {})
    
    if method == 'initialize':
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': 'telegram-mcp', 'version': '1.0.0'},
                'capabilities': {'tools': {}},
            }
        }
    
    elif method == 'tools/list':
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'tools': [
                    {
                        'name': 'send_telegram_message',
                        'description': '通过 Telegram Bot API 发送消息到指定 Chat ID',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'chat_id': {
                                    'type': 'string',
                                    'description': f'Telegram Chat ID (默认: {DEFAULT_CHAT_ID})',
                                },
                                'text': {
                                    'type': 'string',
                                    'description': '要发送的消息内容',
                                },
                            },
                            'required': ['text'],
                        },
                    },
                ],
            }
        }
    
    elif method == 'tools/call':
        tool_name = params.get('name', '')
        arguments = params.get('arguments', {})
        
        if tool_name == 'send_telegram_message':
            chat_id = arguments.get('chat_id', DEFAULT_CHAT_ID)
            text = arguments.get('text', '')
            
            if not chat_id:
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {'code': -32602, 'message': 'chat_id 未提供且无默认值'}
                }
            
            result = send_telegram_message(chat_id, text)
            
            if 'error' in result:
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': {
                        'content': [{'type': 'text', 'text': f"发送失败: {result['error']}"}],
                        'isError': True
                    }
                }
            else:
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': {
                        'content': [{'type': 'text', 'text': f"消息发送成功! message_id: {result['message_id']}"}]
                    }
                }
        else:
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'code': -32601, 'message': f'Tool not found: {tool_name}'}
            }
    
    elif method == 'notifications/initialized':
        return None  # 不需要响应
    
    else:
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'error': {'code': -32601, 'message': f'Method not found: {method}'}
        }


def main():
    """主循环 - 从 stdin 读取请求，输出到 stdout"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    main()
