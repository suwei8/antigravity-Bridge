package main

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"antigravity-bridge/automation"
	"antigravity-bridge/mcp"

	"github.com/joho/godotenv"
	tb "gopkg.in/tucnak/telebot.v2"
)

func main() {
	// IMPORTANT: All logs must go to Stderr because Stdout is MCP
	// DEBUG: Force log to file to check startup
	f, err := os.OpenFile("/tmp/gravity_main_debug.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		log.SetOutput(f)
	} else {
		// Fallback to stderr if file fails
		log.SetOutput(os.Stderr) 
	}

	// Load .env
	err = godotenv.Load()
	if err != nil {
		log.Println("Warning: Error loading .env file, relying on environment variables")
	}

	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		log.Fatal("TELEGRAM_BOT_TOKEN not set")
	}

	b, err := tb.NewBot(tb.Settings{
		Token:  token,
		Poller: &tb.LongPoller{Timeout: 10 * time.Second},
	})
	if err != nil {
		log.Fatal(err)
	}

	// Setup MCP Server
	// Define the function that MCP calls to send to Telegram
	sendToTg := func(chatIDStr, text string) error {
		cid, err := strconv.ParseInt(chatIDStr, 10, 64)
		if err != nil {
			return err
		}
		// We need a recipient object
		// recipient := &tb.User{ID: int(cid)}
		// telebot.ChatID is specific.
		// Let's use Chat object
		chat := &tb.Chat{ID: cid}
		
		// Handle escaped newlines from JSON/LLM specifically
		safeText := strings.ReplaceAll(text, "\\n", "\n")
		
		_, err = b.Send(chat, safeText)
		return err
	}

	mcpServer := mcp.NewServer(sendToTg)
	
	// Start MCP in a generic goroutine or main? 
	// Stdio is blocking. Telegram Poller is blocking.
	// We run Telegram in a routine, MCP runs in main (or vice versa).
	// Stdio listening is better in main to ensure we don't exit early.
	
	// Get executable directory to locate templates (Robust against CWD)
	ex, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	binDir := filepath.Dir(ex)
	templatesDir := filepath.Join(binDir, "templates")
	
	log.Printf("Started. Binary: %s, TemplatesDir: %s, DISPLAY: %s", ex, templatesDir, os.Getenv("DISPLAY"))

	b.Handle(tb.OnText, func(m *tb.Message) {
		msg := m.Text
		log.Printf("Received text from %d: %s", m.Chat.ID, msg)
		
		// Inject Context: We need to inform the AI about the Chat ID so it can reply!
		// We format the message: "[ChatID: 12345] Message content"
		// The AI will see this injected.
		
		contentWithContext := "From Telegram [" + strconv.FormatInt(m.Chat.ID, 10) + "]: " + msg

		go func() {
			// Trigger automation: Visual Paste
			automation.FullWorkflow(contentWithContext, templatesDir, func(status string) {
				// Visual update loop logic "Thinking..."
				// The OLD logic sent directly to Telegram.
				// The NEW logic: We might still want visual feedback "Thinking..."?
				// User requirement: "Replying.png exists -> Send Thinking to Telegram"
				// This implies the Bridge logic *itself* sends "Thinking", 
				// BUT the ACTUAL reply comes from the AI using MCP.
				// So we KEEP the "Thinking" loop here as "Pulse" updates.
				b.Send(m.Sender, status)
			})
		}()
	})

	b.Handle(tb.OnPhoto, func(m *tb.Message) {
		caption := m.Caption
		log.Printf("Received photo with caption: %s", caption)
		
		contentWithContext := "From Telegram [" + strconv.FormatInt(m.Chat.ID, 10) + "]: [Photo] " + caption

		go func() {
			automation.FullWorkflow(contentWithContext, templatesDir, func(status string) {
				b.Send(m.Sender, status)
			})
		}()
	})

	log.Println("Antigravity Bridge Bot & MCP Server Starting...")
	
	// Start Bot in Goroutine
	go b.Start()
	
	log.Printf("Started. DISPLAY: %s", os.Getenv("DISPLAY"))

	// Start MCP Server (Blocking Stdio)
	mcpServer.Start()
}
