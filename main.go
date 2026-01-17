package main

import (
	"fmt"
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
		chat := &tb.Chat{ID: cid}

		// Handle escaped newlines from JSON/LLM specifically
		safeText := strings.ReplaceAll(text, "\\n", "\n")

		_, err = b.Send(chat, safeText)
		return err
	}

	mcpServer := mcp.NewServer(sendToTg)

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

		// Inject Context
		contentWithContext := "From Telegram [" + strconv.FormatInt(m.Chat.ID, 10) + "]: " + msg

		go func() {
			automation.FullWorkflow(contentWithContext, templatesDir, func(status string) {
				// Visual update loop logic "Thinking..."
				b.Send(m.Sender, status)
			})
		}()
	})

	b.Handle(tb.OnPhoto, func(m *tb.Message) {
		log.Printf("Received photo from %d", m.Chat.ID)

		// Download photo
		file := &tb.File{FileID: m.Photo.FileID}
		localPath := filepath.Join(os.TempDir(), fmt.Sprintf("tg_photo_%d.png", time.Now().UnixNano()))

		err := b.Download(file, localPath)
		if err != nil {
			log.Printf("Error downloading photo: %v", err)
			b.Send(m.Chat, "Error downloading photo: "+err.Error())
			return
		}

		// Run Automation with Image
		go func() {
			defer os.Remove(localPath) // Clean up after use
			automation.FullWorkflowImage(localPath, templatesDir, func(status string) {
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
