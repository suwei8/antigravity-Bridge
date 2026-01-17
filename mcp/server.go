package mcp

import (
	"bufio"
	"encoding/json"
	"fmt"
	// "io" removed
	"log"
	"os"
	"sync"
)

// Minimal MCP Protocol implementation
// We need to handle:
// - initialize
// - tools/list
// - tools/call

type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
	ID      interface{}     `json:"id,omitempty"`
}

type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	Result  interface{} `json:"result,omitempty"`
	Error   *JSONRPCError `json:"error,omitempty"`
	ID      interface{} `json:"id"`
}

type JSONRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type Server struct {
	mu           sync.Mutex
	TelegramFunc func(string, string) error // chatID, text
}

func NewServer(tgFunc func(string, string) error) *Server {
	return &Server{
		TelegramFunc: tgFunc,
	}
}

// Start starts the Stdio listener
// NOTE: This blocks, so run in a goroutine or as main loop.
// All logs MUST go to Stderr because Stdout is used for protocol.
func (s *Server) Start() {
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := scanner.Bytes()
		
		var req JSONRPCRequest
		if err := json.Unmarshal(line, &req); err != nil {
			log.Printf("MCP: Error parsing JSON: %v", err)
			continue
		}

		go s.handleRequest(req)
	}
	if err := scanner.Err(); err != nil {
		log.Printf("MCP: Stdin read error: %v", err)
	}
}

func (s *Server) handleRequest(req JSONRPCRequest) {
	var response interface{}
	var err *JSONRPCError

	switch req.Method {
	case "initialize":
		response = map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"serverInfo": map[string]string{
				"name":    "gravity-bridge",
				"version": "1.0.0",
			},
			"capabilities": map[string]interface{}{
				"tools": map[string]interface{}{}, 
			},
		}

	case "tools/list":
		response = map[string]interface{}{
			"tools": []map[string]interface{}{
				{
					"name":        "reply_to_telegram",
					"description": "Send a message reply to a Telegram Chat ID",
					"inputSchema": map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"chat_id": map[string]string{
								"type": "string",
								"description": "The Telegram Chat ID to reply to",
							},
							"text": map[string]string{
								"type": "string",
								"description": "The content of the message",
							},
						},
						"required": []string{"chat_id", "text"},
					},
				},
			},
		}

	case "tools/call":
		// Handle tool execution
		var params struct {
			Name      string            `json:"name"`
			Arguments map[string]string `json:"arguments"`
		}
		if e := json.Unmarshal(req.Params, &params); e != nil {
			err = &JSONRPCError{Code: -32602, Message: "Invalid params"}
			break
		}

		if params.Name == "reply_to_telegram" {
			chatID := params.Arguments["chat_id"]
			text := params.Arguments["text"]
			
			log.Printf("MCP: Calling reply_to_telegram(%s, %s)", chatID, text)
			
			if s.TelegramFunc != nil {
				if e := s.TelegramFunc(chatID, text); e != nil {
					err = &JSONRPCError{Code: -32000, Message: fmt.Sprintf("Telegram Error: %v", e)}
				} else {
					// Success
					response = map[string]interface{}{
						"content": []map[string]string{
							{
								"type": "text",
								"text": "Message sent successfully",
							},
						},
					}
				}
			} else {
				err = &JSONRPCError{Code: -32000, Message: "Telegram function not initialized"}
			}
		} else {
			err = &JSONRPCError{Code: -32601, Message: "Tool not found"}
		}

	default:
		// Optional: notifications or ping
		// For unhandled methods in simple MCP, we might ignore or error
		// Note: "notifications/initialized"
		if req.Method == "notifications/initialized" {
			// Just ack -> nothing to do here really for notification
			return 
		}
		// Method not found
		err = &JSONRPCError{Code: -32601, Message: "Method not found: " + req.Method}
	}

	// Send Response
	resp := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  response,
		Error:   err,
	}
	
	bytes, _ := json.Marshal(resp)
	s.writeOutput(string(bytes))
}

func (s *Server) writeOutput(msg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	fmt.Printf("%s\n", msg)
}
